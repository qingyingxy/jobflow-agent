"""Repeat public campaign checks with a fixed sample and verified source hashes."""
import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from scripts.check_campaign_sources import main as check_sources


def source_hashes():
    paths = [*Path('src').rglob('*.py'), Path(__file__), Path('scripts/check_campaign_sources.py')]
    return {p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


async def main(args):
    folder = Path(args.output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / 'manifest.json'
    if manifest_path.exists():
        raise ValueError('Use a new directory; previous stability evidence must remain intact')
    hashes = source_hashes()
    manifest = {'started_at': datetime.now(UTC).isoformat(), 'companies': args.companies,
                'year': args.year, 'rounds': args.rounds, 'concurrency': args.concurrency,
                'cache_seed': args.cache_from, 'source_hashes': hashes,
                'limits': 'Consecutive checks in one session, with parse-cache reuse and fresh website reads; not multi-day stability or global recall.'}
    save(manifest_path, manifest)
    previous = args.cache_from
    for number in range(1, args.rounds + 1):
        if source_hashes() != hashes:
            raise RuntimeError('Source changed between rounds')
        output = folder / f'round-{number}.json'
        started = datetime.now(UTC).isoformat()
        await check_sources(SimpleNamespace(companies=args.companies, year=args.year,
            concurrency=args.concurrency, cache_from=previous, all_pages=True, output=str(output)))
        data = json.loads(output.read_text(encoding='utf-8'))
        data.update(round=number, started_at=started, finished_at=datetime.now(UTC).isoformat(),
                    cache_from=previous, source_hashes_unchanged=source_hashes() == hashes)
        save(output, data)
        if not data['source_hashes_unchanged']:
            raise RuntimeError('Source changed during a round')
        previous = str(output)
        print(json.dumps({'completed_round': number, 'companies': len(data['results'])}), flush=True)
    save(folder / 'complete.json', {'finished_at': datetime.now(UTC).isoformat(),
                                   'rounds': args.rounds, 'source_hashes_unchanged': source_hashes() == hashes})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--companies', nargs='+', required=True)
    parser.add_argument('--year', type=int, required=True)
    parser.add_argument('--rounds', type=int, default=3, choices=range(2, 6))
    parser.add_argument('--concurrency', type=int, default=2, choices=[1, 2])
    parser.add_argument('--cache-from')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--live', required=True, action='store_true')
    asyncio.run(main(parser.parse_args()))
