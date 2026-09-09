#!/usr/bin/env python3
"""Prepare/verify isolated agent sync scenarios. No agent credentials or prompts saved."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def command(helper, root, *args):
    result = subprocess.run([sys.executable, str(helper), '--repo', str(root), *args],
                            capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup(helper):
    directory = Path(tempfile.mkdtemp(prefix='rag-sync-live-'))
    for agent in ('claude', 'codex'):
        root = directory / agent
        root.mkdir()
        subprocess.run(['git', '-C', str(root), 'init', '-q'], check=True)
        (root / 'auth.py').write_text('LIMIT = 5\n\ndef can_retry(attempts):\n    return attempts < LIMIT\n')
        (root / 'policy.md').write_text('Login retry limit is 5.\n')
        command(helper, root, 'init')
        records = []
        for path, record_id, subject_type, relation, summary in (
            ('auth.py', 'auth-limit', 'symbol', 'implements', 'Login retry limit LIMIT is 5.'),
            ('policy.md', 'auth-policy', 'document', 'documents', 'The policy documents a login retry limit of 5.'),
        ):
            source = command(helper, root, 'source', path)
            source.pop('text')
            subject_id = path + ':LIMIT' if subject_type == 'symbol' else path
            records.append({'id': record_id, 'subject': {'id': subject_id, 'type': subject_type},
                            'relation': relation, 'object': {'id': 'retry-limit', 'type': 'concept'},
                            'summary': summary, 'epistemic': 'observed', 'evidence': [source]})
        batch = root / '.repo-knowledge/seed.json'
        batch.write_text(json.dumps(records))
        command(helper, root, 'put', str(batch))
        plan = command(helper, root, 'sync-plan', '--path', 'auth.py', '--path', 'policy.md')
        review = {'version': 1, 'base_token': plan['base_token'], 'selected_paths': plan['selected_paths'],
                  'files': [{'path': p, 'sha256': digest(root / p), 'review_reason': 'Fixture source verified.'}
                            for p in plan['selected_paths']],
                  'decisions': [{'id': r['id'], 'action': 'keep', 'review_reason': 'Fixture source matches.'}
                                for r in records], 'records': []}
        batch.write_text(json.dumps(review))
        command(helper, root, 'sync-apply', str(batch))
        command(helper, root, 'index')
        gold = {'version': 1, 'id': 'retry-limit', 'answer': '5', 'path': 'auth.py',
                'sha256': digest(root / 'auth.py')}
        (root / '.repo-knowledge/gold.json').write_text(json.dumps(gold))
        (root / 'auth.py').write_text('LIMIT = 6\n\ndef can_retry(attempts):\n    return attempts < LIMIT\n')
        expected = {p: digest(root / p) for p in ('auth.py', 'policy.md', '.repo-knowledge/gold.json')}
        (directory / (agent + '-expected.json')).write_text(json.dumps(expected))
    print(directory)


def verify(helper, directory):
    for agent in ('claude', 'codex'):
        root = directory / agent
        expected = json.loads((directory / (agent + '-expected.json')).read_text())
        for path, original in expected.items():
            assert digest(root / path) == original, (agent, 'source or gold changed', path)
        data = json.loads((root / '.repo-knowledge/knowledge.json').read_text())
        assert data['sync']['reviewed_files']['auth.py'] == digest(root / 'auth.py'), agent
        assert '6' in data['records']['auth-limit']['summary'], (agent, data['records'])
        for record in data['records'].values():
            if 'contradict' in record['summary'].lower():
                assert {'auth.py', 'policy.md'} <= {e['path'] for e in record['evidence']}, (
                    agent, 'contradiction summary lacks both source hashes', record['id'])
        status = command(helper, root, 'status')
        assert status['stale'] == {}, (agent, status)
        query = command(helper, root, 'query', 'login retry limit', '--mode', 'hybrid')
        assert any(r['record']['id'] == 'auth-limit' for r in query['results']), agent
        assert query['vectors']['unindexed_fresh_records'] == 0, query
        result = command(helper, root, 'index')
        assert result['embedded'] == 0, (agent, result)
        print('PASS:', agent, 'updated limit, preserved sources/gold, fresh hybrid retrieval, no-op index')
    print('Manual review still required: policy contradiction handling and gold-invalid report in agent logs.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('setup', 'verify', 'cleanup'))
    parser.add_argument('--helper', type=Path, required=True)
    parser.add_argument('--directory', type=Path)
    args = parser.parse_args()
    if args.action == 'setup':
        setup(args.helper.resolve())
    elif args.action == 'verify':
        verify(args.helper.resolve(), args.directory.resolve())
    else:
        # Delete only these synthetic namespaces; preserve the artifacts for review.
        sys.path.insert(0, str(args.helper.resolve().parent))
        import vectors
        with vectors.connect() as connection:
            for agent in ('claude', 'codex'):
                root = args.directory.resolve() / agent
                assert root.is_dir() and args.directory.name.startswith('rag-sync-live-')
                connection.execute('DELETE FROM repo_knowledge.indexes WHERE repo=%s',
                                   (vectors.namespace(root),))
        print('PASS: synthetic database namespaces removed; logs retained')


if __name__ == '__main__':
    main()
