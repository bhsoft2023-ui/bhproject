/* =====================================================================
   قاعدة بيانات نظام البقالة على SQL Server — BaqalaPOS
   ---------------------------------------------------------------------
   البرنامج ينشئ القاعدة وجداولها تلقائياً عند أول اتصال، ولا حاجة لتشغيل
   هذا الملف يدوياً. يمكن لمسؤول قواعد البيانات تشغيله بنفسه:
       sqlcmd -S .\SQLEXPRESS -E -i BaqalaPOS_SQLServer.sql
   المبالغ BIGINT بوحدة 1/100 ريال يمني، والكميات BIGINT بوحدة 1/1000
   (لدعم الأوزان مثل 0.250 كجم) — دقة كاملة بلا أرقام عائمة.
   ===================================================================== */
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET ANSI_PADDING ON;
SET ANSI_WARNINGS ON;
SET ARITHABORT ON;
SET CONCAT_NULL_YIELDS_NULL ON;
SET NUMERIC_ROUNDABORT OFF;
GO
IF DB_ID(N'BaqalaPOS') IS NULL
    CREATE DATABASE [BaqalaPOS] COLLATE Arabic_CI_AS;
GO
ALTER DATABASE [BaqalaPOS] SET RECOVERY SIMPLE;
ALTER DATABASE [BaqalaPOS] SET AUTO_CLOSE OFF;
ALTER DATABASE [BaqalaPOS] SET PAGE_VERIFY CHECKSUM;
GO
ALTER DATABASE [BaqalaPOS] SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE;
GO
USE [BaqalaPOS];
GO
IF OBJECT_ID(N'dbo.schema_info', N'U') IS NOT NULL
BEGIN
    PRINT N'قاعدة BaqalaPOS موجودة مسبقاً، ولن يُعاد إنشاء الجداول.';
    SET NOEXEC ON;
END
GO
-- @@schema: ما بعد هذا السطر هو المخطط (الإصدار 1) الذي ينفذه البرنامج داخل معاملة واحدة
CREATE TABLE dbo.schema_info (
    version    INT          NOT NULL,
    applied_at DATETIME2(0) NOT NULL CONSTRAINT DF_schema_info_applied DEFAULT SYSDATETIME()
);
GO
CREATE TABLE dbo.settings (
    [key]  NVARCHAR(100) NOT NULL CONSTRAINT PK_settings PRIMARY KEY,
    value  NVARCHAR(MAX) NOT NULL
);
GO
CREATE TABLE dbo.users (
    id                   INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_users PRIMARY KEY,
    username             NVARCHAR(50)  NOT NULL CONSTRAINT UQ_users_username UNIQUE,
    full_name            NVARCHAR(100) NOT NULL CONSTRAINT DF_users_full_name DEFAULT N'',
    password_hash        NVARCHAR(255) NOT NULL,
    role                 NVARCHAR(10)  NOT NULL CONSTRAINT CK_users_role CHECK (role IN (N'admin', N'cashier')),
    active               BIT           NOT NULL CONSTRAINT DF_users_active DEFAULT 1,
    must_change_password BIT           NOT NULL CONSTRAINT DF_users_mcp DEFAULT 0,
    created_at           DATETIME2(0)  NOT NULL
);
GO
CREATE TABLE dbo.categories (
    id   INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_categories PRIMARY KEY,
    name NVARCHAR(100) NOT NULL CONSTRAINT UQ_categories_name UNIQUE
);
GO
CREATE TABLE dbo.products (
    id           INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_products PRIMARY KEY,
    name         NVARCHAR(200) NOT NULL,
    name_norm    NVARCHAR(200) NOT NULL,
    barcode      NVARCHAR(64)  NULL,
    category_id  INT           NULL CONSTRAINT FK_products_category REFERENCES dbo.categories(id) ON DELETE SET NULL,
    unit         NVARCHAR(20)  NOT NULL CONSTRAINT DF_products_unit DEFAULT N'حبة',
    is_weighted  BIT           NOT NULL CONSTRAINT DF_products_weighted DEFAULT 0,
    sell_price   BIGINT        NOT NULL CONSTRAINT CK_products_sell CHECK (sell_price >= 0),
    cost_price   BIGINT        NOT NULL CONSTRAINT DF_products_cost DEFAULT 0 CONSTRAINT CK_products_cost CHECK (cost_price >= 0),
    min_qty      BIGINT        NOT NULL CONSTRAINT DF_products_min DEFAULT 0 CONSTRAINT CK_products_min CHECK (min_qty >= 0),
    track_expiry BIT           NOT NULL CONSTRAINT DF_products_track DEFAULT 0,
    active       BIT           NOT NULL CONSTRAINT DF_products_active DEFAULT 1,
    created_at   DATETIME2(0)  NOT NULL,
    updated_at   DATETIME2(0)  NOT NULL
);
GO
-- الباركود فريد عند وجوده فقط (يُسمح بعدة أصناف بلا باركود)
CREATE UNIQUE INDEX UX_products_barcode ON dbo.products(barcode) WHERE barcode IS NOT NULL;
CREATE INDEX IX_products_name ON dbo.products(name_norm);
CREATE INDEX IX_products_category ON dbo.products(category_id);
GO
CREATE TABLE dbo.price_history (
    id         INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_price_history PRIMARY KEY,
    product_id INT          NOT NULL CONSTRAINT FK_price_history_product REFERENCES dbo.products(id) ON DELETE CASCADE,
    old_price  BIGINT       NOT NULL,
    new_price  BIGINT       NOT NULL,
    user_id    INT          NULL CONSTRAINT FK_price_history_user REFERENCES dbo.users(id),
    changed_at DATETIME2(0) NOT NULL
);
CREATE INDEX IX_price_history_product ON dbo.price_history(product_id);
GO
CREATE TABLE dbo.customers (
    id              INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_customers PRIMARY KEY,
    name            NVARCHAR(200)  NOT NULL,
    phone           NVARCHAR(50)   NOT NULL CONSTRAINT DF_customers_phone DEFAULT N'',
    address         NVARCHAR(400)  NOT NULL CONSTRAINT DF_customers_address DEFAULT N'',
    credit_limit    BIGINT         NOT NULL CONSTRAINT DF_customers_limit DEFAULT 0 CONSTRAINT CK_customers_limit CHECK (credit_limit >= 0),
    opening_balance BIGINT         NOT NULL CONSTRAINT DF_customers_opening DEFAULT 0,
    notes           NVARCHAR(1000) NOT NULL CONSTRAINT DF_customers_notes DEFAULT N'',
    active          BIT            NOT NULL CONSTRAINT DF_customers_active DEFAULT 1,
    created_at      DATETIME2(0)   NOT NULL
);
GO
CREATE TABLE dbo.suppliers (
    id              INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_suppliers PRIMARY KEY,
    name            NVARCHAR(200)  NOT NULL,
    phone           NVARCHAR(50)   NOT NULL CONSTRAINT DF_suppliers_phone DEFAULT N'',
    address         NVARCHAR(400)  NOT NULL CONSTRAINT DF_suppliers_address DEFAULT N'',
    opening_balance BIGINT         NOT NULL CONSTRAINT DF_suppliers_opening DEFAULT 0,
    notes           NVARCHAR(1000) NOT NULL CONSTRAINT DF_suppliers_notes DEFAULT N'',
    active          BIT            NOT NULL CONSTRAINT DF_suppliers_active DEFAULT 1,
    created_at      DATETIME2(0)   NOT NULL
);
GO
CREATE TABLE dbo.purchases (
    id            INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_purchases PRIMARY KEY,
    supplier_id   INT            NULL CONSTRAINT FK_purchases_supplier REFERENCES dbo.suppliers(id),
    purchase_type NVARCHAR(10)   NOT NULL CONSTRAINT CK_purchases_type CHECK (purchase_type IN (N'cash', N'credit', N'opening')),
    total         BIGINT         NOT NULL CONSTRAINT CK_purchases_total CHECK (total >= 0),
    paid          BIGINT         NOT NULL CONSTRAINT CK_purchases_paid CHECK (paid >= 0),
    note          NVARCHAR(1000) NOT NULL CONSTRAINT DF_purchases_note DEFAULT N'',
    user_id       INT            NULL CONSTRAINT FK_purchases_user REFERENCES dbo.users(id),
    created_at    DATETIME2(0)   NOT NULL,
    CONSTRAINT CK_purchases_paid_total CHECK (paid <= total),
    CONSTRAINT CK_purchases_credit_supplier CHECK (purchase_type <> N'credit' OR supplier_id IS NOT NULL)
);
CREATE INDEX IX_purchases_supplier ON dbo.purchases(supplier_id);
CREATE INDEX IX_purchases_date ON dbo.purchases(created_at);
GO
-- دفعات المخزون: أساس FEFO وتتبع الصلاحية وتكلفة البضاعة المباعة
CREATE TABLE dbo.batches (
    id            INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_batches PRIMARY KEY,
    product_id    INT          NOT NULL CONSTRAINT FK_batches_product REFERENCES dbo.products(id),
    purchase_id   INT          NULL CONSTRAINT FK_batches_purchase REFERENCES dbo.purchases(id),
    qty_received  BIGINT       NOT NULL CONSTRAINT CK_batches_received CHECK (qty_received > 0),
    qty_remaining BIGINT       NOT NULL CONSTRAINT CK_batches_remaining CHECK (qty_remaining >= 0),
    unit_cost     BIGINT       NOT NULL CONSTRAINT CK_batches_cost CHECK (unit_cost >= 0),
    expiry_date   DATE         NULL,
    received_at   DATETIME2(0) NOT NULL,
    CONSTRAINT CK_batches_remaining_received CHECK (qty_remaining <= qty_received)
);
CREATE INDEX IX_batches_fefo ON dbo.batches(product_id, expiry_date, received_at) INCLUDE (qty_remaining, unit_cost);
CREATE INDEX IX_batches_purchase ON dbo.batches(purchase_id);
GO
CREATE TABLE dbo.sales (
    id          INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_sales PRIMARY KEY,
    sale_type   NVARCHAR(10) NOT NULL CONSTRAINT CK_sales_type CHECK (sale_type IN (N'cash', N'credit')),
    customer_id INT          NULL CONSTRAINT FK_sales_customer REFERENCES dbo.customers(id),
    user_id     INT          NOT NULL CONSTRAINT FK_sales_user REFERENCES dbo.users(id),
    total       BIGINT       NOT NULL CONSTRAINT CK_sales_total CHECK (total >= 0),
    paid        BIGINT       NOT NULL CONSTRAINT CK_sales_paid CHECK (paid >= 0),
    cost_total  BIGINT       NOT NULL CONSTRAINT DF_sales_cost DEFAULT 0,
    created_at  DATETIME2(0) NOT NULL,
    CONSTRAINT CK_sales_paid_total CHECK (paid <= total),
    CONSTRAINT CK_sales_credit_customer CHECK (sale_type = N'cash' OR customer_id IS NOT NULL),
    CONSTRAINT CK_sales_cash_paid CHECK (sale_type = N'credit' OR paid = total)
);
CREATE INDEX IX_sales_date ON dbo.sales(created_at);
CREATE INDEX IX_sales_customer ON dbo.sales(customer_id);
GO
CREATE TABLE dbo.sale_items (
    id           INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_sale_items PRIMARY KEY,
    sale_id      INT           NOT NULL CONSTRAINT FK_sale_items_sale REFERENCES dbo.sales(id) ON DELETE CASCADE,
    product_id   INT           NOT NULL CONSTRAINT FK_sale_items_product REFERENCES dbo.products(id),
    product_name NVARCHAR(200) NOT NULL,
    unit         NVARCHAR(20)  NOT NULL,
    qty          BIGINT        NOT NULL CONSTRAINT CK_sale_items_qty CHECK (qty > 0),
    unit_price   BIGINT        NOT NULL,
    line_total   BIGINT        NOT NULL,
    cost_total   BIGINT        NOT NULL
);
CREATE INDEX IX_sale_items_sale ON dbo.sale_items(sale_id);
CREATE INDEX IX_sale_items_product ON dbo.sale_items(product_id);
GO
CREATE TABLE dbo.sale_item_batches (
    id           INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_sale_item_batches PRIMARY KEY,
    sale_item_id INT    NOT NULL CONSTRAINT FK_sib_item REFERENCES dbo.sale_items(id) ON DELETE CASCADE,
    batch_id     INT    NOT NULL CONSTRAINT FK_sib_batch REFERENCES dbo.batches(id),
    qty          BIGINT NOT NULL CONSTRAINT CK_sib_qty CHECK (qty > 0),
    unit_cost    BIGINT NOT NULL
);
CREATE INDEX IX_sib_item ON dbo.sale_item_batches(sale_item_id);
CREATE INDEX IX_sib_batch ON dbo.sale_item_batches(batch_id);
GO
CREATE TABLE dbo.customer_payments (
    id          INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_customer_payments PRIMARY KEY,
    customer_id INT            NOT NULL CONSTRAINT FK_cpay_customer REFERENCES dbo.customers(id),
    amount      BIGINT         NOT NULL CONSTRAINT CK_cpay_amount CHECK (amount > 0),
    note        NVARCHAR(1000) NOT NULL CONSTRAINT DF_cpay_note DEFAULT N'',
    user_id     INT            NULL CONSTRAINT FK_cpay_user REFERENCES dbo.users(id),
    created_at  DATETIME2(0)   NOT NULL
);
CREATE INDEX IX_cpay_customer ON dbo.customer_payments(customer_id);
GO
CREATE TABLE dbo.supplier_payments (
    id          INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_supplier_payments PRIMARY KEY,
    supplier_id INT            NOT NULL CONSTRAINT FK_spay_supplier REFERENCES dbo.suppliers(id),
    amount      BIGINT         NOT NULL CONSTRAINT CK_spay_amount CHECK (amount > 0),
    note        NVARCHAR(1000) NOT NULL CONSTRAINT DF_spay_note DEFAULT N'',
    user_id     INT            NULL CONSTRAINT FK_spay_user REFERENCES dbo.users(id),
    created_at  DATETIME2(0)   NOT NULL
);
CREATE INDEX IX_spay_supplier ON dbo.supplier_payments(supplier_id);
GO
CREATE TABLE dbo.expenses (
    id           INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_expenses PRIMARY KEY,
    category     NVARCHAR(100)  NOT NULL,
    amount       BIGINT         NOT NULL CONSTRAINT CK_expenses_amount CHECK (amount > 0),
    description  NVARCHAR(1000) NOT NULL CONSTRAINT DF_expenses_desc DEFAULT N'',
    expense_date DATE           NOT NULL,
    user_id      INT            NULL CONSTRAINT FK_expenses_user REFERENCES dbo.users(id),
    created_at   DATETIME2(0)   NOT NULL
);
CREATE INDEX IX_expenses_date ON dbo.expenses(expense_date);
GO
-- إتلاف/تسوية المخزون (منتهي، تالف، فرق جرد)
CREATE TABLE dbo.stock_adjustments (
    id         INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_stock_adjustments PRIMARY KEY,
    product_id INT           NOT NULL CONSTRAINT FK_adj_product REFERENCES dbo.products(id),
    batch_id   INT           NULL CONSTRAINT FK_adj_batch REFERENCES dbo.batches(id),
    qty_change BIGINT        NOT NULL,
    unit_cost  BIGINT        NOT NULL CONSTRAINT DF_adj_cost DEFAULT 0,
    reason     NVARCHAR(400) NOT NULL,
    user_id    INT           NULL CONSTRAINT FK_adj_user REFERENCES dbo.users(id),
    created_at DATETIME2(0)  NOT NULL
);
CREATE INDEX IX_adj_product ON dbo.stock_adjustments(product_id);
CREATE INDEX IX_adj_date ON dbo.stock_adjustments(created_at);
GO
CREATE VIEW dbo.customer_balances AS
SELECT c.id AS customer_id,
       c.opening_balance
       + COALESCE((SELECT SUM(s.total - s.paid) FROM dbo.sales s WHERE s.customer_id = c.id), 0)
       - COALESCE((SELECT SUM(p.amount) FROM dbo.customer_payments p WHERE p.customer_id = c.id), 0)
       AS balance
FROM dbo.customers c;
GO
CREATE VIEW dbo.supplier_balances AS
SELECT s.id AS supplier_id,
       s.opening_balance
       + COALESCE((SELECT SUM(pu.total - pu.paid) FROM dbo.purchases pu WHERE pu.supplier_id = s.id), 0)
       - COALESCE((SELECT SUM(p.amount) FROM dbo.supplier_payments p WHERE p.supplier_id = s.id), 0)
       AS balance
FROM dbo.suppliers s;
GO
INSERT INTO dbo.schema_info (version) VALUES (1);
GO
SET NOEXEC OFF;
GO
