## diagram

* `id`: Định danh sơ đồ.
* `name`: Tên sơ đồ.
* `viewport`: Thông tin hiển thị toàn cảnh sơ đồ.
  * `x`, `y`: Tọa độ gốc (offset).
  * `zoom`: Mức phóng to/thu nhỏ (0.1 → 5.0).
  * `gridSize`: Kích thước lưới.
  * `snapToGrid`: Có tự động bắt vào lưới không.
* `nodes*`: Danh sách node (bảng hoặc ghi chú).
* `edges*`: Danh sách cạnh (mũi tên FK hoặc liên kết ghi chú).

---

## node

* `id*`: Định danh node (chuỗi không rỗng).
* `type*`: `"table"`, `"note"`, `"sticky-note"`, `"text-label"`, `"drawing-path"`.
* `position*`: Tọa độ trên canvas (`x`, `y`).
* `size*`: Kích thước (`w`, `h`; minimum 20×20).
* `zIndex`: Lớp hiển thị.
* `style`: Style cơ bản (`class`, `stroke`, `fill`, `fontSize`).
* `name`: Tên hiển thị của node (thường là tên bảng).

### table node (type = "table")

* `tableId*`: Tham chiếu `table.id` trong model.json (chuỗi không rỗng).
* `columns`: Thứ tự và trang trí cột hiển thị.
  * `columnId*`: Tham chiếu `column.id` trong model.json (chuỗi không rỗng).
  * `label`: Tên hiển thị nếu khác tên gốc.
  * `decorations`: Style cột.
    * `pk`: Cột PK (gạch chân).
    * `ck`: Cột candidate key.
    * `fk`: Cột FK (đánh dấu).

### note node (type = "note")

* `text`: Nội dung ghi chú.

---

## edge

* `id*`: Định danh cạnh (chuỗi không rỗng).
* `type*`: `"fk"` hoặc `"noteLink"`.
* `source*`: ID column nguồn (chuỗi không rỗng).
* `target*`: ID column đích (chuỗi không rỗng).
* `sourceSide`: Phía kết nối column nguồn (`left` / `right`).
* `targetSide`: Phía kết nối column đích (`left` / `right`).
* `points`: Polyline — danh sách điểm (`x`, `y`) vẽ đường uốn lượn.
* `style`: Style đường (`stroke`, `fill`, `class`).
* `fkRef`: Tham chiếu FK cụ thể trong model.json (bắt buộc nếu type = `fk`).
  * `tableId`: ID bảng chứa FK (chuỗi không rỗng).
  * `foreignKeyIndex`: Chỉ số của cột FK trong mảng columns của bảng nguồn (≥ 0).
* `labels`: Text hiển thị trên cạnh.
  * `text`: Nội dung.
  * `position`: Tọa độ đặt label (`x`, `y`).

## Storage envelope

```json
{ "diagram": { "nodes": [], "edges": [] } }
```

- `nodes` and `edges` are required arrays; `id` and `name` on `diagram` are optional.
- IDs and references are non-empty strings; UUIDs and generated edge/column-handle IDs are accepted.
- Annotation types include `sticky-note`, `text-label`, and `drawing-path`, with an optional `data` object.
- Model data describes entities/tables and their semantics; diagram data describes layout, rendering, edges, and annotations.
- Column decorations: `pk`, `ck`, `fk`; older payloads may also contain `underline`/`italic`. Edge `sourceSide`/`targetSide` values are `left` or `right`.
