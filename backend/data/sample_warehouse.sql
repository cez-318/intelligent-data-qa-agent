-- Fictional fixture matching the original project schema. Never a production dump.
CREATE TABLE dim_region (
  region_id INT PRIMARY KEY, province VARCHAR(40), region_name VARCHAR(40), country VARCHAR(40)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE dim_customer (
  customer_id INT PRIMARY KEY, customer_name VARCHAR(40), gender VARCHAR(10), member_level VARCHAR(20)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE dim_product (
  product_id INT PRIMARY KEY, product_name VARCHAR(80), category VARCHAR(40), brand VARCHAR(40)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE dim_date (
  date_id INT PRIMARY KEY, year INT, quarter VARCHAR(8), month INT, day INT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE fact_order (
  order_id INT PRIMARY KEY, customer_id INT, product_id INT, date_id INT, region_id INT,
  order_quantity INT, order_amount DECIMAL(18,2),
  FOREIGN KEY (customer_id) REFERENCES dim_customer(customer_id),
  FOREIGN KEY (product_id) REFERENCES dim_product(product_id),
  FOREIGN KEY (date_id) REFERENCES dim_date(date_id),
  FOREIGN KEY (region_id) REFERENCES dim_region(region_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE qa_fixture_manifest (dataset VARCHAR(100) PRIMARY KEY) ENGINE=InnoDB;
START TRANSACTION;
INSERT INTO dim_region VALUES (1,'广东','华南','中国'),(2,'北京','华北','中国');
INSERT INTO dim_customer VALUES (1,'虚构客户甲','未知','普通'),(2,'虚构客户乙','未知','高级');
INSERT INTO dim_product VALUES (1,'示例键盘','办公用品','示例品牌'),(2,'示例显示器','电子产品','示例品牌');
INSERT INTO dim_date VALUES (20260901,2026,'Q3',9,1),(20250901,2025,'Q3',9,1);
INSERT INTO fact_order VALUES
  (1,1,1,20260901,1,1,100),(2,2,2,20260901,1,1,300),(3,1,2,20260901,2,1,200),
  (4,1,1,20250901,1,1,100),(5,2,1,20250901,2,1,100);
INSERT INTO qa_fixture_manifest VALUES ('fictional_ecommerce_v1_five_orders');
COMMIT;
