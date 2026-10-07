## model (Thông tin mô hình)

- `id*`: ID mô hình không rỗng; giữ nguyên UUID/ID đã lưu. ID mới nên dùng `cid_`.
- `name*`: Tên mô hình.
- `version*`: Phiên bản (integer ≥ 1).
- `notes`: Ghi chú.

## entity (Thực thể)

- `id*`: ID thực thể (chuỗi không rỗng; ID mới nên dùng `cid_`).
- `name*`: Tên thực thể.
- `kind`: Loại thực thể (`strong`, `weak`). Mặc định: `strong`.
- `attributes*`: Tập các thuộc tính của thực thể — mỗi phần tử là **object** (xem `attribute`).
- `notes`: Ghi chú nghiệp vụ.

## attribute (Thuộc tính)

- `id*`: ID thuộc tính (chuỗi không rỗng; ID mới nên dùng `cid_`).
- `name*`: Tên thuộc tính.
- `kind*`: Loại thuộc tính (`simple`, `composite`, `multi_valued`, `complex`, `derived`).
- `isKey*`: Có phải thuộc tính khóa hay không (boolean).
- `semantics`: Tag ngữ nghĩa mô tả ý nghĩa nghiệp vụ.
- `components`: Tập các thuộc tính con nếu `kind = composite | complex`.
  - `id*`: ID thuộc tính con (chuỗi không rỗng; ID mới nên dùng `cid_`).
  - `name*`: Tên thuộc tính con.
  - Cùng cấu trúc `attribute`, gồm `id`, `name`, `kind`, `isKey`; có thể lồng thêm `components`.
- `derivation`: Công thức tính nếu `kind = derived`.
- `notes`: Ghi chú nghiệp vụ.

## relationship (Quan hệ)

- `id*`: ID quan hệ (chuỗi không rỗng; ID mới nên dùng `cid_`).
- `name*`: Tên quan hệ.
- `type*`: Loại quan hệ (`association`, `identifying`).
- `arity`: Bậc quan hệ (integer ≥ 1).
- `ends*`: Tập các entity tham gia quan hệ — mỗi phần tử là **object** (xem `relEnd`).
- `attributes`: Thuộc tính của quan hệ (cùng format với `attribute`).
- `semantics`: Mô tả ngữ nghĩa nghiệp vụ.
- `notes`: Ghi chú nghiệp vụ.

## relEnd (Đầu mút quan hệ)

- `entityId*`: ID của thực thể tham gia (chuỗi không rỗng; ID mới nên dùng `cid_`).
- `role`: Vai trò của thực thể trong quan hệ (**CHỈ dùng cho quan hệ đệ quy** — khi cả hai đầu mút cùng entityId).
- `cardinality`: Ký hiệu lượng số (`"1"`, `"N"`, `"M"`, `"1..N"`, v.v.).
- `optional`: Bắt buộc (`false`) / Tùy chọn (`true`).

### Quan hệ đệ quy (Recursive / Self-referencing Relationships)

Khi cả hai đầu mút (`ends`) cùng trỏ đến **cùng một entity** (cùng `entityId`), đây là quan hệ đệ quy.
Mỗi đầu mút **BẮT BUỘC** phải có trường `role` khác nhau để phân biệt hai phía.

**Ví dụ** — Employee quản lý Employee khác:
```json
{
  "id": "cid_rel_manages",
  "name": "manages",
  "type": "association",
  "ends": [
    { "entityId": "cid_employee", "role": "manager", "cardinality": "1", "optional": false },
    { "entityId": "cid_employee", "role": "subordinate", "cardinality": "N", "optional": false }
  ]
}
```

**Quy tắc**:
- Luôn điền `role` cho quan hệ đệ quy — không bao giờ để trống.
- Hai `role` phải mang ý nghĩa nghiệp vụ rõ ràng (ví dụ: `manager`/`subordinate`, `parent`/`child`, `prerequisite`/`dependent`).

## generalization (Tổng quát hóa)

- `id*`: ID (chuỗi không rỗng; ID mới nên dùng `cid_`).
- `parentEntityIds*`: Mảng ID của các thực thể cha (ít nhất 1), hỗ trợ nhiều cha.
- `childEntityIds*`: Mảng ID của thực thể con; có thể rỗng khi đang chỉnh canvas.
- `categoryBy`: Tiêu chí phân loại thực thể.
- `constraints*`: Các ràng buộc cha-con.
  - `disjointness*`: `disjoint` hoặc `overlap`.
  - `completeness*`: `total` hoặc `partial`.

## category (Thể loại / Union)

- `id*`: ID (chuỗi không rỗng; ID mới nên dùng `cid_`).
- `categoryEntityId`: ID của category entity (chuỗi không rỗng; ID mới nên dùng `cid_`).
- `superclassEntityIds*`: Tập các ID của superclass entities; có thể rỗng khi đang chỉnh canvas.
- `completeness*`: `total` hoặc `partial`.
- `notes`: Ghi chú.

## Payload rules

- Required root fields: `model`, `entities`, `relationships`. Optional root fields: `generalizations`, `categories`, `constraints` (array), `notes`, `tags`.
- New ISA output uses `parentEntityIds`. Older payloads may use singular `parentEntityId`; at least one of these fields must exist.
- Include `kind` on every new entity and `kind`/`isKey` on every new attribute, recursively through `components`. Legacy component attributes may omit `isKey`.
- Optional relationship-end `notes` are accepted for older payloads.
- Empty models and partially connected ISA/category definitions are valid storage states. Complete generated designs still need valid keys and references.
- Preserve existing IDs and metadata unless the requested edit changes them.
