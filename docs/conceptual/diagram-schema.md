## diagram (Sơ đồ tổng thể)

* `id*`: ID sơ đồ.
* `name*`: Tên sơ đồ.
* `viewport`: Cấu hình khung nhìn.

  * `x, y`: Tọa độ offset.
  * `zoom`: Mức phóng to/thu nhỏ.
  * `gridSize`: Kích thước lưới căn chỉnh.
  * `snapToGrid`: Bật/tắt chế độ hút vào lưới.
* `nodes*`: Tập các node trong sơ đồ.
* `edges*`: Tập các cạnh nối giữa các node.

---

## node

* `id*`: ID node.
* `type*`: Loại node (`entity`, `relationship`, `attribute`, `isaCircle`, `unionCircle`, `note`).
* `position*`: Vị trí node trên canvas (`x`, `y`).
* `size*`: Kích thước node (`w`, `h`).
* `zIndex`: Thứ tự lớp vẽ.
* `style`: Thuộc tính hiển thị (stroke, fill, class).
* `name`: Văn bản hiển thị trong khối (tên entity/attr/relationship).

### entity node

* `entityId*`: Tham chiếu đến `model.entities[].id`.
* `entityRender.doubleStroke`: `true` nếu là weak entity (hình chữ nhật viền đôi).

### relationship node

* `relationshipId*`: Tham chiếu đến `model.relationships[].id`.
* `relationshipRender.doubleStroke`: `true` nếu là identifying relationship (hình thoi viền đôi).

### attribute node

* `attributeId*`: Tham chiếu đến `model.attributes[].id`.
* `attributeRender`: Các ký hiệu hiển thị cho oval.

  * `doubleEllipse`: Oval kép (multi-valued hoặc complex parent).
  * `dashed`: Oval nét đứt (derived).
  * `underline`: Gạch chân (key).
  * `underlineStyle`: `solid` = key thường, `dashed` = partial key.

### isaCircle node

* `isaCircle.symbol*`: Ký hiệu trong vòng tròn (`d` = disjoint, `o` = overlap).

### unionCircle node

* `unionCircle.symbol*`: Luôn = `"U"`.
* `unionCircle.categoryId*`: Tham chiếu đến `model.categories[].id`.

### note node

* `text*`: Nội dung ghi chú tự do.

---

## edge (Cạnh nối)

* `id*`: ID cạnh.
* `type*`: Loại cạnh.

  * `participation`: entity <-> relationship.
  * `attrOf`: attribute <-> entity/relationship.
  * `componentOf`: attribute con <-> attribute composite/complex.
  * `isaParent`: entity cha <-> isaCircle.
  * `isaChild`: isaCircle <-> entity con.
  * `categoryLink`: categoryEntity <-> unionCircle.
  * `categoryMember`: unionCircle <-> superclass entity.
* `relationshipId`: Tham chiếu model.relationships (nếu type=participation).
* `generalizationId`: Tham chiếu model.generalizations (nếu type=isaParent/isaChild).
* `categoryId`: Tham chiếu model.categories (nếu type=categoryLink/categoryMember).
* `from*`: Đầu mút nguồn (`nodeId`, `portId`).
* `to*`: Đầu mút đích (`nodeId`, `portId`).
* `labels`: Văn bản hiển thị trên cạnh (`nearFrom`, `center`, `nearTo`).
* `style`: Tuỳ chọn chung (ví dụ `dashed`).
* `endStyle`: Trang trí riêng cho mỗi đầu mút.

  * `from.doubleLine`: true = mandatory participation.
  * `from.marker`: `one` = 1 gạch, `many` = 3 gạch.
  * `to.doubleLine`: true = mandatory.
  * `to.marker`: `one`/`many`.

