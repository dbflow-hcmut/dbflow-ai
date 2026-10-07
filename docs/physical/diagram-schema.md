## diagram

* `id`: Định danh sơ đồ (chuỗi không rỗng).
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
  * `columnId*`: ID hiển thị theo dạng `pid_${tableId}_col_${index}`; có thể khác ID gốc của column trong model.
  * `label`: Tên hiển thị nếu khác tên gốc.
  * `decorations`: Style cột.
    * `pk`: Cột PK (gạch chân).
    * `fk`: Cột FK (đánh dấu).
    * `underline`: Ép hiển thị gạch chân.
    * `italic`: Hiển thị in nghiêng.

### note node (type = "note")

* `text`: Nội dung ghi chú.

---

## edge

* `id*`: Định danh cạnh (chuỗi không rỗng).
* `type*`: `"fk"` hoặc `"noteLink"`.
* `source*`: ID node nguồn (chuỗi không rỗng).
* `target*`: ID node đích (chuỗi không rỗng).
* `points`: Polyline — danh sách điểm (`x`, `y`) vẽ đường uốn lượn.
* `style`: Style đường (`stroke`, `fill`, `class`).
* `fkRef`: Tham chiếu FK cụ thể trong model.json (bắt buộc nếu type = `fk`).
  * `tableId`: ID bảng chứa FK (chuỗi không rỗng).
  * `foreignKeyIndex`: Chỉ số của cột FK trong mảng columns của bảng nguồn (≥ 0).
  * `sourceColumnName`: Tên cột nguồn.
  * `targetColumnName`: Tên cột đích.
  * `onDelete`: Hành vi khi xóa (`NO ACTION`, `CASCADE`, `SET NULL`, `SET DEFAULT`, `RESTRICT`).
  * `onUpdate`: Hành vi khi cập nhật (`NO ACTION`, `CASCADE`, `SET NULL`, `SET DEFAULT`, `RESTRICT`).
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
- Table `data` stores full column properties and indexes (`data.columns`, `data.indexes`). Visual `columns` stores labels/decorations and does not replace those properties.
