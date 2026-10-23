"""Load only new dw_retail_ii/meta_retail_ii in the named local project container.

No DROP/TRUNCATE, no overwrite of existing tables, no passwords on argv/stdout.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import duckdb
from retail_pipeline import DATA, digest

CONTAINER = 'qa-opt-mysql'
ROOT = Path(__file__).resolve().parents[1]
TABLES = {
    'dim_date': 'date_id INT PRIMARY KEY, year INT, month INT, day INT, `year_month` VARCHAR(7)',
    'dim_country': 'country VARCHAR(128) COLLATE utf8mb4_bin PRIMARY KEY',
    'dim_product': 'stock_code VARCHAR(64) COLLATE utf8mb4_bin PRIMARY KEY, product_name TEXT',
    'fact_retail_line': '''line_id BIGINT PRIMARY KEY, invoice_no VARCHAR(64) COLLATE utf8mb4_bin,
      stock_code VARCHAR(64) COLLATE utf8mb4_bin, customer_id VARCHAR(64) COLLATE utf8mb4_bin,
      date_id INT, country VARCHAR(128) COLLATE utf8mb4_bin, quantity BIGINT,
      unit_price DECIMAL(20,6), signed_amount DECIMAL(24,6), sale_amount DECIMAL(24,6),
      sale_units BIGINT, sale_invoice VARCHAR(64) COLLATE utf8mb4_bin,
      sale_customer VARCHAR(64) COLLATE utf8mb4_bin, cancel_amount DECIMAL(24,6),
      cancel_invoice VARCHAR(64) COLLATE utf8mb4_bin,
      INDEX idx_date(date_id), INDEX idx_country_date(country,date_id),
      INDEX idx_stock_date(stock_code,date_id), INDEX idx_invoice(sale_invoice)''',
}


def mysql(docker, sql):
    command = 'export MYSQL_PWD="$(cat "$MYSQL_ROOT_PASSWORD_FILE")"; exec mysql -uroot --default-character-set=utf8mb4 --batch --raw --skip-column-names'
    result = subprocess.run([docker, 'exec', '-i', CONTAINER, 'sh', '-c', command],
                            input=sql, text=True, encoding='utf-8', capture_output=True, timeout=240)
    if result.returncode:
        # Only expose the numeric server error; diagnostics may contain credentials.
        import re
        code = re.search(r'ERROR (\d+)', result.stderr)
        raise RuntimeError('RETAIL_MYSQL_ERROR_' + (code.group(1) if code else 'UNKNOWN'))
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker', required=True)
    parser.add_argument('--confirm-new-retail-databases', required=True, action='store_true')
    args = parser.parse_args()
    inspected = subprocess.run([args.docker, 'inspect', CONTAINER, '--format', '{{index .Config.Labels "com.docker.compose.project"}}'], capture_output=True, text=True, timeout=15)
    if inspected.returncode or inspected.stdout.strip() != 'intelligent-qa-optimized':
        raise RuntimeError('NOT_ISOLATED_CONTAINER')
    quality = json.loads((DATA / 'quality.json').read_text(encoding='utf-8'))
    if digest(DATA / 'normalized_rows.csv') != quality['normalized_csv_sha256']:
        raise RuntimeError('NORMALIZED_HASH_CHANGED')
    if mysql(args.docker, 'SELECT @@secure_file_priv;') != '/var/lib/mysql-files/':
        raise RuntimeError('UNEXPECTED_MYSQL_IMPORT_DIRECTORY')
    count = int(mysql(args.docker, "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema IN ('dw_retail_ii','meta_retail_ii');"))
    if count:
        raise RuntimeError('RETAIL_DATABASES_NOT_EMPTY_NO_OVERWRITE')
    expected_users = mysql(args.docker, "SELECT CONCAT(user,'@',host) FROM mysql.user WHERE user IN ('metadata_owner','qa_readonly') ORDER BY user;")
    if expected_users.splitlines() != ['metadata_owner@%', 'qa_readonly@%']:
        raise RuntimeError('UNEXPECTED_LOCAL_ACCOUNTS')
    mysql(args.docker, '''CREATE DATABASE IF NOT EXISTS dw_retail_ii CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
      CREATE DATABASE IF NOT EXISTS meta_retail_ii CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
      GRANT SELECT ON dw_retail_ii.* TO 'qa_readonly'@'%';
      GRANT ALL PRIVILEGES ON meta_retail_ii.* TO 'metadata_owner'@'%';''')
    db = duckdb.connect(str(DATA / 'reference.duckdb'), read_only=True)
    records = []
    for table, ddl in TABLES.items():
        print('Preparing import: ' + table, flush=True)
        output = DATA / f'mysql_{table}.csv'
        if output.exists():
            raise RuntimeError('EXPORT_EXISTS_NO_OVERWRITE')
        sentinel = '__QA_RETAIL_NULL_781302__'
        db.execute(f"COPY {table} TO '{output.as_posix()}' (FORMAT CSV, HEADER FALSE, NULL '{sentinel}', FORCE_QUOTE *)")
        copied = subprocess.run([args.docker, 'cp', str(output), f'{CONTAINER}:/var/lib/mysql-files/qa_retail_{table}.csv'], capture_output=True, timeout=90)
        if copied.returncode:
            raise RuntimeError('CONTAINER_COPY_FAILED')
        columns = [r[0] for r in db.execute(f'DESCRIBE {table}').fetchall()]
        variables = ','.join('@v'+str(i) for i in range(len(columns)))
        assignment = ','.join(f"`{col}`=NULLIF(@v{i},'{sentinel}')" for i, col in enumerate(columns))
        sql = f'''USE dw_retail_ii;
          CREATE TABLE {table} ({ddl}) ENGINE=InnoDB;
          LOAD DATA INFILE '/var/lib/mysql-files/qa_retail_{table}.csv' INTO TABLE {table}
          CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY '"'
          LINES TERMINATED BY '\\n' ({variables}) SET {assignment};
          SELECT @@warning_count;
          SELECT COUNT(*) FROM {table};'''
        outcome = mysql(args.docker, sql).splitlines()
        expected = db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        if outcome != ['0', str(expected)]:
            raise RuntimeError('IMPORT_WARNINGS_OR_ROW_MISMATCH_' + table)
        records.append({'table': table, 'rows': expected, 'export_sha256': digest(output)})
        print(f'Imported {table}: {expected:,} rows, zero warnings', flush=True)
    # Cross-engine exact comparisons catch decimal parsing, null and sign mistakes.
    aggregate = 'SELECT COUNT(*), SUM(sale_amount), SUM(cancel_amount), SUM(quantity), COUNT(DISTINCT sale_invoice), COUNT(DISTINCT sale_customer), SUM(customer_id IS NULL) FROM fact_retail_line'
    expected = [str(value) for value in db.execute(aggregate).fetchone()]
    actual = mysql(args.docker, 'USE dw_retail_ii; ' + aggregate + ';').split('\t')
    if actual != expected:
        raise RuntimeError('IMPORT_AGGREGATE_MISMATCH')
    mysql(args.docker, "CREATE TABLE dw_retail_ii.qa_dataset_manifest (dataset VARCHAR(64) PRIMARY KEY, source_sha256 CHAR(64)); INSERT INTO dw_retail_ii.qa_dataset_manifest VALUES ('uci_retail_ii_v1','" + quality['source_xlsx_sha256'] + "');")
    db.close()
    report = {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'database': 'dw_retail_ii',
              'tables': records, 'cross_engine_aggregates_match': True, 'original_databases_unchanged': True}
    (DATA / 'mysql_import.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Import and independent cross-engine aggregate verification passed.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        raise SystemExit(str(error) if isinstance(error, RuntimeError) else type(error).__name__) from None
