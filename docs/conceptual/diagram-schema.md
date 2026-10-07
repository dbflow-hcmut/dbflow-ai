## CRITICAL: Node ID Convention

Node IDs identify the model elements represented in the diagram:
- Entity node: node id = `entityId` (falls back to `id` if missing).
- Relationship node: node id = `relationshipId` (falls back to `id`).
- Attribute node: node id = `attributeId` (falls back to `id`).

**Therefore, for each node the `id` field MUST be the same value as its linked model ID:**
- Entity node: `id` = `entityId` = the entity's id from model.json.
- Relationship node: `id` = `relationshipId` = the relationship's id from model.json.
- Attribute node: `id` = `attributeId` = the attribute's id from model.json.

Edge `from.nodeId` and `to.nodeId` reference these IDs.

Example:
```json
// Entity node: id === entityId
{ "id": "cid_student", "type": "entity", "entityId": "cid_student", ... }

// Attribute node: id === attributeId
{ "id": "cid_stu_name", "type": "attribute", "attributeId": "cid_stu_name", ... }

// Edge connecting them
{ "id": "cid_edge_1", "type": "attrOf", "from": { "nodeId": "cid_stu_name" }, "to": { "nodeId": "cid_student" } }
```

---

## CRITICAL: Completeness Rule

The diagram MUST contain nodes and edges for ALL elements defined in model.json:
1. One **entity node** for each entity in `model.entities`.
2. One **attribute node** for each attribute in every entity's `attributes` array.
3. One **attrOf edge** connecting each attribute node to its owner entity node.
4. One **relationship node** for each relationship in `model.relationships`.
5. One **participation edge** for each end in a relationship's `ends` array (connecting the entity node to the relationship node, with `labels.nearFrom`/`labels.nearTo` for cardinality).
6. If a relationship has `attributes`, include attribute nodes + attrOf edges for those too.
7. For composite/complex attributes with `components`, include attribute nodes + componentOf edges.

---

## diagram (Sơ đồ tổng thể)

* `id`: ID sơ đồ (chuỗi không rỗng).
* `name`: Tên sơ đồ.
* `viewport`: Cấu hình khung nhìn.
  * `x, y`: Tọa độ offset.
  * `zoom`: Mức phóng to/thu nhỏ.
  * `gridSize`: Kích thước lưới căn chỉnh.
  * `snapToGrid`: Bật/tắt chế độ hút vào lưới.
* `nodes*`: Tập các node trong sơ đồ.
* `edges*`: Tập các cạnh nối giữa các node.

---

## node

* `id*`: ID node (chuỗi không rỗng). MUST equal `entityId`/`relationshipId`/`attributeId` (see convention above).
* `type*`: Loại node (`entity`, `relationship`, `attribute`, `isaCircle`, `unionCircle`, `note`, `sticky-note`, `text-label`, `drawing-path`).
* `position*`: Vị trí node trên canvas (`x`, `y`).
* `size*`: Kích thước node (`w`, `h`). Minimum: 20×20. Recommended: entity 120×60, relationship 110×50, attribute 90×40.
* `zIndex`: Thứ tự lớp vẽ.
* `style`: Thuộc tính hiển thị (stroke, fill, class, meta).
  * `meta.entity.variant`: `single` / `double` / `dashed`.
  * `meta.entity.fields`: Danh sách field hiển thị trên entity.
  * `meta.relationship.variant`: `single` / `double` / `dashed`.
  * `meta.relationship.cardinalities`: Map entityId → cardinality string.
  * `meta.attribute.variant`: `single` / `double` / `dashed`.
  * `meta.attribute.isKey`: boolean.
* `name`: Văn bản hiển thị trong khối (tên entity/attr/relationship).

### entity node

* `entityId*`: MUST equal node `id`. Tham chiếu đến `model.entities[].id` (chuỗi không rỗng).
* `entityRender.doubleStroke`: `true` nếu là weak entity (hình chữ nhật viền đôi).

### relationship node

* `relationshipId*`: MUST equal node `id`. Tham chiếu đến `model.relationships[].id` (chuỗi không rỗng).
* `relationshipRender.doubleStroke`: `true` nếu là identifying relationship (hình thoi viền đôi).

### attribute node

* `attributeId*`: MUST equal node `id`. Tham chiếu đến attribute id trong model (chuỗi không rỗng).
* `attributeRender`: Các ký hiệu hiển thị cho oval.
  * `doubleEllipse`: Oval kép (multi-valued hoặc complex parent).
  * `dashed`: Oval nét đứt (derived).
  * `underline`: `true` nếu `isKey = true` trong model.
  * `underlineStyle`: `solid` = key thường, `dashed` = partial key.

### isaCircle node

* `isaCircle.symbol*`: Ký hiệu trong vòng tròn (`d` = disjoint, `o` = overlap).

### unionCircle node

* `unionCircle.symbol*`: Luôn = `"U"`.
* `unionCircle.categoryId`: Tham chiếu đến `model.categories[].id`.

### note node

* `text*`: Nội dung ghi chú tự do.

---

## edge (Cạnh nối)

* `id*`: ID cạnh (chuỗi không rỗng).
* `type*`: Loại cạnh:
  * `participation`: entity ↔ relationship (normal).
  * `attrOf`: attribute ↔ entity/relationship (connects attribute to its owner).
  * `componentOf`: attribute con ↔ attribute composite/complex.
  * `identifying`: entity ↔ relationship (identifying, bracket line style).
  * `isaParent`: entity cha ↔ isaCircle.
  * `isaChild`: isaCircle ↔ entity con, hoặc direct entity ↔ entity generalization có bracket.
  * `categoryLink`: categoryEntity ↔ unionCircle.
  * `categoryMember`: unionCircle ↔ superclass entity.
* `relationshipId`: Tham chiếu model.relationships (nếu type = `participation` hoặc `identifying`).
* `generalizationId`: Tham chiếu model.generalizations (bắt buộc nếu type = `isaParent` / `isaChild`). Với d/o circle, edge không có bracket là parent, edge có bracket là child. Entity → entity edge luôn được lưu như direct identifying/bracket generalization edge; `generalizationId` bằng chính `id` của edge; đầu mút có bracket là parent entity, đầu còn lại là child entity. Mặc định bracket ở `from`, nên `from.nodeId` là parent entity và `to.nodeId` là child entity nếu người dùng không đổi direction.
* `categoryId`: Tham chiếu model.categories (bắt buộc nếu type = `categoryLink` / `categoryMember`). Với u circle, edge không có bracket là superclass, edge có bracket là category entity.
* `from*`: Đầu mút nguồn.
  * `nodeId*`: ID node nguồn = entityId/relationshipId/attributeId (chuỗi không rỗng).
  * `portId`: Cổng kết nối (`top`, `bottom`, `left`, `right`).
* `to*`: Đầu mút đích.
  * `nodeId*`: ID node đích = entityId/relationshipId/attributeId (chuỗi không rỗng).
  * `portId`: Cổng kết nối (`top`, `bottom`, `left`, `right`).
* `labels`: Văn bản hiển thị trên cạnh.
  * `nearFrom`: Nhãn gần đầu mút nguồn (thường là cardinality).
  * `center`: Nhãn giữa cạnh.
  * `nearTo`: Nhãn gần đầu mút đích (thường là cardinality).
* `endStyle`: Trang trí riêng cho mỗi đầu mút.
  * `from.doubleLine`: `true` = mandatory participation.
  * `from.marker`: `none` / `one` / `many`.
  * `from.bracket`: `true` = bracket line (identifying relationship).
  * `to.doubleLine`: `true` = mandatory participation.
  * `to.marker`: `none` / `one` / `many`.
  * `to.bracket`: `true` = bracket line (identifying relationship).

## Storage envelope

```json
{ "diagram": { "nodes": [], "edges": [] } }
```

- `nodes` and `edges` are required arrays; `id` and `name` on `diagram` are optional.
- IDs and references are non-empty strings; UUIDs and generated edge/column-handle IDs are accepted.
- Annotation types include `sticky-note`, `text-label`, and `drawing-path`, with an optional `data` object.
- Model data describes entities/tables and their semantics; diagram data describes layout, rendering, edges, and annotations.
- `style.meta` stores entity/relationship/attribute rendering hints. Inline `fields`/`columns` are accepted in older payloads. Direct `isaChild` edges may connect two entities; bracket ends identify the parent.
