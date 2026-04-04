
### 5.1. Tổng quan 

---

### 5.2. Nhóm `physical` (root object)

**`physical`** là root object của file, chứa toàn bộ thông tin schema vật lý đã reverse từ DDL.

* `id`: định danh nội bộ cho physical schema (pattern `phid_…`).
  Dùng để tham chiếu trong hệ thống (version control, vector DB).
* `name`: tên schema vật lý (ví dụ: `ecommerce_physical_v1`).
* `description`: mô tả ngắn về schema (VD: “Physical schema reverse từ DB sản phẩm”).
* `dbms`: loại hệ quản trị CSDL (`postgres`, `mysql`, `sqlserver`,…).
* `version`: số version (nguyên) của physical schema (phục vụ versioning).
* `defaultDatabase`: tên database mặc định (nếu có nhiều database trong cùng file).
* `metadata`:

  * `createdBy`, `createdAt`: thông tin ai tạo, lúc nào.
  * `updatedBy`, `updatedAt`: thông tin cập nhật gần nhất.
  * `sourceHash`: hash của input DDL/metadata, giúp phát hiện thay đổi.
  * `tags`: các tag tuỳ chọn (VD: `["prod", "legacy", "customer-domain"]`).
* `source`: tham chiếu tới nhóm `sourceInfo` (xem 5.7).
* `warnings`: danh sách cảnh báo toàn cục (xem 5.7).
* `databases`: danh sách các CSDL (`$defs.database`), mỗi database chứa nhiều schema, bảng, view,…

---

### 5.3. Nhóm cấp CSDL: `database` và `dbSchema`

#### 5.3.1. Định nghĩa `database`

Một **`database`** tương ứng với một CSDL trong DBMS (Postgres/MySQL).

* `id`: định danh nội bộ (`phid_db_…`).
* `name`: tên database thực tế (VD: `app_db`, `mimic_iv`).
* `comment`: ghi chú thêm (VD: môi trường, domain).
* `schemas`: danh sách các schema con (`$defs.dbSchema`).


#### 5.3.2. Định nghĩa `dbSchema`

Một **`dbSchema`** biểu diễn schema/namespace bên trong database (VD: `public`, `sales`, `dbo`).

* `id`: định danh nội bộ (`phid_schema_…`).
* `name`: tên schema (VD: `public`, `sales`, `dbo`).
* `comment`: mô tả ngắn.
* `tables`: danh sách các bảng (`$defs.table`).
* `views`: danh sách view (`$defs.view`).
* `sequences`: sequence (`$defs.sequence`).
* `triggers`: trigger ở cấp schema (nhiều DBMS gắn trigger theo bảng, nhưng vẫn cho phép biểu diễn ở đây).
* `functions`: function/procedure.

---

### 5.4. Nhóm bảng & cột: `table`, `column`, constraint, index, partition, storage

#### 5.4.1. Định nghĩa `table`

**`table`** là đối tượng cốt lõi, ánh xạ trực tiếp với bảng vật lý trong DBMS.

* `id`: định danh nội bộ (`phid_table_…`).
* `name`: tên bảng (VD: `customer`, `orders`).
* `comment`: mô tả bảng (nếu DBMS hỗ trợ comment).
* `columns`: danh sách cột (`$defs.column`).
* `primaryKey`: khoá chính (`$defs.primaryKey`).
* `uniqueConstraints`: danh sách ràng buộc unique (`$defs.uniqueConstraint`).
* `foreignKeys`: danh sách khoá ngoại (`$defs.foreignKey`).
* `checkConstraints`: danh sách constraint CHECK (`$defs.checkConstraint`).
* `indexes`: danh sách index (`$defs.index`).
* `partitioning`: cấu hình partition (`$defs.partitioning`).
* `storage`: thông tin storage (`$defs.storageOptions`).
* `options`: các option DB-specific khác (VD: MySQL ENGINE, CHARSET,…).
* `source`: thông tin nguồn DDL (file, line, statementId; xem `objectSource`).
* `logicalMappable`: flag cho biết bảng này có thể map sang logical/ERD như thế nào.

**Vai trò:**

* Ở bước 2, mỗi `table` sẽ là một **candidate relation** trong Relational schema.
* `primaryKey`, `foreignKeys`, `checkConstraints` là nguồn chính để suy ra entity/relationship ở bước 3.
* `partitioning`, `storage`, `indexes` vẫn được giữ lại cho các use-case vật lý (tối ưu hoá, AI phân tích performance), dù không map lên ERD.

#### 5.4.2. Định nghĩa `column`

**`column`** biểu diễn cột vật lý trong bảng.

* `id`: định danh nội bộ (`phid_col_…`).
* `name`: tên cột (VD: `customer_id`, `email`).
* `position`: vị trí cột trong bảng (bắt đầu từ 1).
* `dataTypeOriginal`: kiểu dữ liệu gốc (VD: `VARCHAR(255)`, `NUMBER(10,2)`).
* `dataTypeNormalized`: kiểu dữ liệu đã chuẩn hoá (`string`, `integer`, `decimal`, `date`, `timestamp`,…).
* `length`, `precision`, `scale`: thông số chi tiết (nếu có).
* `nullable`: cho phép NULL hay không.
* `default`: giá trị mặc định (literal hoặc biểu thức).
* `isIdentity`: có phải cột identity/auto increment không.
* `isGenerated`: cột được generate (computed column).
* `collation`: collation áp dụng (nếu có).
* `comment`: mô tả cột (nếu có).
* `physicalOnly`: cột chỉ phục vụ vật lý (VD: cột phân vùng, cột system).
* `logicalMappable`: flag map logic (true/false/…).
* `vendorSpecific`: object tuỳ ý cho option DB-specific (VD: `generated always as`, `on update current_timestamp`).


#### 5.4.3. Khoá và ràng buộc: `primaryKey`, `uniqueConstraint`, `foreignKey`, `checkConstraint`

**`primaryKey`**

* `name`: tên constraint PK.
* `columns`: danh sách tên cột tạo thành PK.
* `deferrable`, `initiallyDeferred`: thông tin ràng buộc trì hoãn (nếu DBMS hỗ trợ).
* `logicalMappable`: mặc định `"always"`.

---

**`uniqueConstraint`**

* `name`: tên constraint UNIQUE.
* `columns`: danh sách cột unique.
* `logicalMappable`: có thể là `"candidate"` nếu muốn suy ra candidate key.

---

**`foreignKey`**

* `name`: tên constraint FK.
* `columns`: cột local.
* `refSchema`: schema của bảng tham chiếu.
* `refTable`: tên bảng tham chiếu.
* `refColumns`: danh sách cột được tham chiếu.
* `onDelete`, `onUpdate`: hành vi khi xóa/cập nhật (CASCADE, SET NULL,…).
* `deferrable`, `initiallyDeferred`: như PK.
* `logicalMappable`: `"always"`.

---

**`checkConstraint`**

* `name`: tên constraint CHECK.
* `expression`: biểu thức logic (text).
* `logicalMappable`: thường `"always"` hoặc `"candidate"`.

#### 5.4.4. `index`

**`index`** mô tả các chỉ mục vật lý.

* `name`: tên index.
* `columns`: cột tham gia index (theo thứ tự).
* `unique`: index có unique hay không.
* `method`: phương thức index (BTREE, HASH,…).
* `wherePredicate`: điều kiện (partial index).
* `includedColumns`: cột include thêm (covering index, SQL Server).
* `logicalMappable`: thường `"never"` hoặc `"candidate"` nếu muốn suy unique.
* `vendorSpecificFlags`: các flag như `PARTIAL_INDEX`, `CLUSTERED`,…

#### 5.4.5. `partitioning`

**`partitioning`** mô tả chiến lược phân vùng bảng.

* `strategy`: kiểu partition (`RANGE`, `LIST`, `HASH`, `OTHER`).
* `expression`: biểu thức partition (VD: `order_date`, `hash(customer_id)`).
* `partitions`: danh sách partition:

  * `name`: tên partition.
  * `from`, `to`: range (nếu là RANGE).
  * `values`: danh sách giá trị (nếu LIST).
  * `tablespace`: nơi lưu trữ partition.
* `logicalMappable`: gần như `"never"`.

#### 5.4.6. `storageOptions`

**`storageOptions`** mô tả các tham số storage DB-specific.

* `tablespace`: tablespace (Oracle/Postgres).
* `filegroup`: filegroup (SQL Server).
* `fillfactor`: fill factor (Postgres).
* `compression`: chế độ nén.
* `other`: object chứa các option khác.
* `logicalMappable`: `"never"`.

---

### 5.5. Nhóm đối tượng khác: `view`, `sequence`, `trigger`, `function`

#### 5.5.1. `view`

**`view`** mô tả view và materialized view.

* `id`: định danh (`phid_view_…`).
* `name`: tên view.
* `comment`: mô tả.
* `definition`: câu lệnh SQL định nghĩa view.
* `baseTables`: danh sách bảng nền (nếu phân tích được).
* `isMaterialized`: có phải mview không.
* `storage`: storage của mview (nếu có).
* `logicalMappable`: thường `"never"` (trừ khi có rule đặc biệt).
* `source`: thông tin nguồn.

#### 5.5.2. `sequence`

**`sequence`** mô tả sequence sinh số.

* `id`, `name`: định danh.
* `increment`, `minValue`, `maxValue`, `startValue`, `cache`, `cycle`: các thông số sequence.
* `logicalMappable`: thông thường `"never"` (vì đây là chi tiết implement của PK).
* `source`: nguồn DDL.

#### 5.5.3. `trigger`

**`trigger`** mô tả các trigger của bảng/schema.

* `id`, `name`: định danh.
* `table`: tên bảng gắn trigger.
* `schema`: schema chứa bảng.
* `timing`: `BEFORE`, `AFTER`, `INSTEAD OF`,…
* `events`: danh sách sự kiện (`INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`).
* `function`: tên function/procedure được gọi.
* `definition`: body định nghĩa (text).
* `logicalMappable`: `"never"` (trong phạm vi đồ án).
* `source`: nguồn DDL.

#### 5.5.4. `function`

**`function`** (hoặc procedure) mô tả các hàm/stored procedure.

* `id`, `name`: định danh.
* `schema`: schema chứa function.
* `returnType`: kiểu trả về (nếu là function).
* `language`: ngôn ngữ (SQL, PL/pgSQL, PL/SQL,…).
* `isDeterministic`: có deterministic hay không.
* `body`: code body (text).
* `logicalMappable`: `"never"`.
* `source`: nguồn.

---

### 5.6. Nhóm `sourceInfo`, `objectSource`, `warning`, `logicalMappable`, `dbms`

#### 5.6.1. `sourceInfo` (nguồn dữ liệu đầu vào)

**`sourceInfo`** mô tả nguồn mà từ đó physical schema được reverse.

* `type`: `"ddl_script"`, `"live_connection"`, `"other"`.
* `dialectDetected`: DBMS phát hiện được (áp dụng heuristic hoặc do user chọn).
* `files`: danh sách file DDL:

  * `path`: đường dẫn file.
  * `hash`: hash nội dung.
  * `size`: kích thước.
* `connection`: thông tin kết nối (nếu reverse trực tiếp từ DB):

  * `host`, `port`, `database`, `user`.


#### 5.6.2. `objectSource` (nguồn của từng object)

**`objectSource`** được gắn vào từng bảng, view, trigger, function,…

* `ddlFragment`: đoạn text DDL tương ứng (phần `CREATE TABLE…`).
* `file`: file chứa đoạn này.
* `line`: số dòng bắt đầu.
* `statementId`: id nội bộ của statement.

#### 5.6.3. `warning` (hệ thống cảnh báo)

**`warning`** mô tả một cảnh báo phát sinh trong quá trình reverse.

* `code`: mã cảnh báo (VD: `DDL_PARSE_ERROR`, `DDL_UNCERTAIN_TYPE_MAPPING`,…).
* `severity`: mức độ (`info`, `warning`, `error`).
* `message`: mô tả chi tiết, hướng dẫn user.
* `location`: vị trí trong input:

  * `file`, `line`, `statementId`.
* `objectRef`: tham chiếu tới object liên quan:

  * `kind`: loại object (`table`, `column`, `index`,…).
  * `database`, `schema`, `table`, `column`, `name`: khoá nhận diện.

#### 5.6.4. `logicalMappable` (cờ map logic)

**`logicalMappable`** là một trong những trường quan trọng nhất để xử lý việc “đi ngược chiều” và tránh mất thông tin mà user không biết.

* Kiểu: `boolean` hoặc string, với các giá trị:

  * `true` / `"always"`: luôn map được sang logical/ERD.
  * `false` / `"never"`: không map sang logical/ERD (thuần vật lý).
  * `"candidate"`: có **tiềm năng** map, nhưng cần user hoặc rule quyết định.

Hầu hết:

* `table`, `column`, `primaryKey`, `foreignKey`, `checkConstraint` -> `"always"`.
* `uniqueConstraint`, một số `index unique` -> `"candidate"`.
* `partitioning`, `storageOptions`, đa số `index`, `trigger`, `function`, `sequence` -> `"never"`.


#### 5.6.5. `dbms` (loại hệ quản trị)

**`dbms`** là enum cho phép chuẩn hoá tên hệ quản trị CSDL:

* Các giá trị: `postgres`, `mysql`, `mariadb`, `sqlserver`, `oracle`, `sqlite`, `bigquery`, `snowflake`, `db2`, `other`.

---
