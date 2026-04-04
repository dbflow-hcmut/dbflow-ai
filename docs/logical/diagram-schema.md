## diagram

- `id`: định danh của sơ đồ (prefix `lid_`).
- `name`: tên sơ đồ
- `viewport`: thông tin hiển thị toàn cảnh sơ đồ.
  - `x`, `y`: tọa độ gốc (offset).
  - `zoom`: mức phóng to/thu nhỏ (0.1 → 5.0).
  - `gridSize`: kích thước lưới.
  - `snapToGrid`: có tự động bắt vào lưới không.
- `nodes`: danh sách node (mỗi node có thể là bảng hoặc ghi chú).
- `edges`: danh sách cạnh (mũi tên FK hoặc liên kết ghi chú).

## node

- `id`: định danh node (prefix `lid_`).
- `type`: `"table"` hoặc `"note"`.
- `position`: tọa độ trên canvas (x,y).
- `size`: kích thước (w,h).
- `zIndex`: lớp hiển thị (cái nào chồng lên trên).
- `style`: style cơ bản (stroke, fill, font size, class CSS).
- `name`: tên hiển thị của node (thường là tên bảng).
- `tableId`: trỏ về `table.id` trong `model.json` (bắt buộc khi type=table).
- `columns`: dùng để quy định thứ tự và trang trí cột hiển thị trong bảng (chỉ cho type=table).

  - `columnId`: tham chiếu đến `column.id` trong `model.json`.
  - `label`: tên hiển thị nếu khác tên gốc.
  - `decorations`: để style cột (pk, fk, underline, italic).

    - `pk`: cột PK (gạch chân).
    - `fk`: cột FK (thường đánh dấu).
    - `underline`: ép hiển thị gạch chân.
    - `italic`: hiển thị in nghiêng.

- `text`: nội dung ghi chú (chỉ cho type=note).

## edge

- `id`: định danh cạnh (prefix `lid_`).
- `type`: `"fk"` hoặc `"noteLink"`.
- `source`: id node nguồn.
- `target`: id node đích.
- `points`: polyline (một danh sách điểm) để vẽ đường đi uốn lượn.
- `style`: style đường (stroke, fill, class…).
- `fkRef`: tham chiếu tới foreign key cụ thể trong `model.json` (bắt buộc nếu type=fk).

  - `tableId`: id bảng chứa FK.
  - `foreignKeyIndex`: chỉ số trong mảng `table.foreignKeys`.

- `labels`: text hiển thị trên cạnh.

  - `text`: nội dung.
  - `position`: tọa độ đặt label.

## Khác

- `point`: đối tượng `{x,y}` để định vị.
- `size`: `{w,h}` cho kích thước node.
- `style`: `{class, stroke, fill, fontSize}` để tùy chỉnh.
