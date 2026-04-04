## entity (Thực thế)

- `id*`: ID thực thể.
- `name*`: Tên thực thể.
- `kind`: Loại thực thể (strong, weak).
- `attributes*`: Tập các thuộc tính của thực thể.
- `notes`: Ghi chú nghiệp vụ…

## attribute (Thuộc tính)

- `id*`: ID thuộc tính.
- `name*`: Tên thuộc tính.
- `kind*`: Loại thuộc tính (simple, composite, multi_valued, complex, derived).
- `isKey*`: Có phải thuộc tính khóa hay không.
- `semantics`: Tag ngữ nghĩa mô tả ý nghĩa nghiệp vụ.
- `components`: Tập các thuộc tính con nếu `kind = [composite | complex]`.
  - `id`: ID thuộc tính.
  - `name`: Tên thuộc tính.
  - `kind`: Loại thuộc tính (simple).
- `derivation`: Công thức tính nếu `kind = [derived]`.
- `notes`: Ghi chú nghiệp vụ…

## relationship (Quan hệ)

- `id*`: ID quan hệ.
- `name*`: Tên quan hệ.
- `type*`: Loại quan hệ (association, identifying).
- `arity`: Bậc quan hệ.
- `ends*`: Tập các entity nodes của quan hệ.
- `attributes`: Thuộc tính của quan hệ.
- `semantics`: Tag ngữ nghĩa mô tả ý nghĩa nghiệp vụ.
- `notes`: Ghi chú nghiệp vụ…

## relEnd (Entity nodes của quan hệ)

- `entityId*`: ID của thực thể tương ứng.
- `role`: Vai trò của thực thể trong quan hệ (thường cần khi là quan hệ đệ quy, quan hệ cha - con giữa thực thể mạnh - yếu).
- `cardinality*`: Số lượng instance mà 1 thực thể có thể tham gia.
- `optional`: Bắt buộc/Tùy chọn.

## generalization

- `id*`: ID.
- `parentEntityId*`: ID của thực thể cha.
- `childEntityIds*`: Tập các ID của thực thể con.
- `categoryBy`: Tiêu chí phân loại thực thể (nếu có).
- `constraints*`: Các ràng buộc cha-con.
  - `disjointness*`: (disjointness, overlap).
  - `completeness*`: (total, partial).

## category

- `id*`: ID.
- `categoryEntityId*`: ID của category entity.
- `superclassEntityIds*`: Tập các ID của superclass entities.
- `completeness*`: (total, partial).
