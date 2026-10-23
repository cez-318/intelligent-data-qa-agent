"""Read-only installation, public-data quality and profile isolation audit."""
import argparse
from datetime import datetime, timezone
import json
import duckdb
import httpx
from load_retail_mysql import mysql
from retail_pipeline import DATA, ROOT, profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker', required=True)
    args = parser.parse_args()
    db = duckdb.connect(str(DATA / 'reference.duckdb'), read_only=True)
    result = profile(db)
    result['invoice_multi_country'] = db.execute('SELECT COUNT(*) FROM (SELECT invoice_no FROM raw_lines GROUP BY invoice_no HAVING COUNT(DISTINCT country)>1)').fetchone()[0]
    result['invoice_multi_customer'] = db.execute('SELECT COUNT(*) FROM (SELECT invoice_no FROM raw_lines GROUP BY invoice_no HAVING COUNT(DISTINCT customer_id)>1)').fetchone()[0]
    result['missingness_pct'] = {key: round(result[key]/result['raw_rows']*100, 4) for key in ('missing_customers','missing_descriptions','duplicate_extra_rows')}
    result['orphan_counts'] = db.execute('SELECT SUM(d.date_id IS NULL),SUM(c.country IS NULL),SUM(p.stock_code IS NULL) FROM fact_retail_line f LEFT JOIN dim_date d ON f.date_id=d.date_id LEFT JOIN dim_country c ON f.country=c.country LEFT JOIN dim_product p ON f.stock_code=p.stock_code').fetchone()
    result['sales_summary'] = db.execute('SELECT SUM(sale_amount),COUNT(DISTINCT sale_invoice),SUM(cancel_amount),COUNT(DISTINCT sale_customer) FROM fact_retail_line').fetchone()
    db.close()
    rows = mysql(args.docker, "SELECT 'original_orders',COUNT(*) FROM dw.fact_order UNION ALL SELECT 'retail_lines',COUNT(*) FROM dw_retail_ii.fact_retail_line UNION ALL SELECT 'retail_metrics',COUNT(*) FROM meta_retail_ii.metric_info UNION ALL SELECT 'original_metrics',COUNT(*) FROM meta.metric_info;")
    result['mysql_counts'] = dict(line.split('\t') for line in rows.splitlines())
    grants = mysql(args.docker, "SHOW GRANTS FOR 'qa_readonly'@'%';").splitlines()
    result['reader_select_only'] = all(g.startswith('GRANT SELECT ON ') or g.startswith('GRANT USAGE ON ') for g in grants)
    assert result['reader_select_only']
    assert result['mysql_counts']['original_orders'] == '5'
    assert result['mysql_counts']['retail_lines'] == '1067371'
    with httpx.Client(trust_env=False, timeout=30) as client:
        result['app_health'] = client.get('http://127.0.0.1:8000/api/health').json()
        result['unauthorized_status'] = client.post('http://127.0.0.1:8000/api/query', json={'query':'2010年的销售额'}).status_code
        assert result['unauthorized_status'] == 401
        result['vector_counts'] = {}
        for name in ['retail-ii-column-v1','retail-ii-metric-v1','data-agent-column','data-agent-metric']:
            response = client.get(f'http://127.0.0.1:16333/collections/{name}')
            response.raise_for_status()
            result['vector_counts'][name] = response.json()['result']['points_count']
        response = client.get('http://127.0.0.1:19200/retail-ii-values-v1/_count')
        response.raise_for_status()
        result['value_count'] = response.json()['count']
    result['checked_at_utc'] = datetime.now(timezone.utc).isoformat()
    destination = ROOT / 'reports' / 'retail_installation_audit.json'
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'monthly','app_health'}}, ensure_ascii=True, default=str))


if __name__ == '__main__':
    main()
