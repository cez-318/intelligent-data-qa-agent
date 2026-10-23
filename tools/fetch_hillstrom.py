"""Fetch the publisher's public RCT CSV without using application credentials."""
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'http://www.minethatdata.com/Kevin_Hillstrom_MineThatData_E-MailAnalytics_DataMiningChallenge_2008.03.20.csv'
PAGE = 'https://blog.minethatdata.com/2008/03/minethatdata-e-mail-analytics-and-data.html'


def main():
    directory = ROOT / 'datasets/hillstrom'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / 'hillstrom.csv'
    if target.exists():
        print('Existing dataset retained; no overwrite.')
        return
    with urllib.request.urlopen(SOURCE, timeout=45) as response:
        data = response.read(10_000_001)
        final_url = response.url
    if len(data) > 10_000_000:
        raise ValueError('SOURCE_TOO_LARGE')
    rows = list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
    if len(rows) != 64000 or set(rows[0]) != {'recency','history_segment','history','mens','womens','zip_code','newbie','channel','segment','visit','conversion','spend'}:
        raise ValueError('UNEXPECTED_SOURCE_SCHEMA_OR_SIZE')
    target.write_bytes(data)
    manifest = {'source_url': SOURCE, 'resolved_url':final_url, 'source_description':PAGE,
                'downloaded_at_utc':datetime.now(timezone.utc).isoformat(),
                'sha256':hashlib.sha256(data).hexdigest(), 'rows':len(rows), 'bytes':len(data),
                'randomization_basis':'Publisher reports random allocation 1/3 per arm; assignment logs unavailable.',
                'transport_note':'Publisher HTTP link; HTTPS failed certificate verification, which was not disabled. SHA256 pins downloaded bytes, not publisher authenticity.',
                'license_note':'Public challenge download; no explicit redistribution license found on the source page. Do not assume unrestricted redistribution.'}
    (directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=True))


if __name__ == '__main__':
    main()
