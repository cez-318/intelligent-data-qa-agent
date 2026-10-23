"""Run the existing application or indexer with the isolated real-data profile."""
import argparse
import asyncio
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['serve', 'index'])
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    os.environ['DATA_AGENT_PROFILE'] = 'retail_ii'
    if args.action == 'index':
        from app.scripts.init_metadata import initialize
        from app.scripts.build_meta_knowledge import build
        from improved.profiles import active_profile
        async def indexing():
            await initialize()
            await build(active_profile().conf / 'meta_config.yaml')
        asyncio.run(indexing())
    else:
        import uvicorn
        uvicorn.run('main:app', host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit(f'Retail action failed: {type(error).__name__}; credentials not displayed.') from None
