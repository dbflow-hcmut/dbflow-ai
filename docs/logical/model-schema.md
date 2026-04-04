## `table`

* `id`: định danh bảng (prefix `lid_`).
* `name`: tên bảng.
* `columns`: danh sách các cột của bảng.
* `functionalDependencies`: danh sách FD nội bộ của chính bảng này .
* `notes`: ghi chú.


## `column`

* `id`: định danh cột (prefix `lid_`).
* `name`: tên cột.
* `nullable`: cho phép `NULL` hay không (mặc định `true`).
* `unique`: `true/false` – UNIQUE đơn cột.
* `roles`: các vai trò khóa của cột:
  * `primaryKey`: `true/false` – cột tham gia PK của bảng.
  * `foreignKey`: nếu cột là FK thì khai báo:
    * `refTableId`: `id` bảng đích (prefix `lid_`).
    * `refColumnId`: `id` cột đích (prefix `lid_`).
  * `candidateKey`: `true/false` – cột tham gia một candidate key.
* `notes`: ghi chú.


## `functionalDependency`
* `id`: định danh FD (prefix `lid_`).
* `name`: tên FD (tuỳ chọn).
* `left`: mảng `column.id` – determinant.
* `right`: mảng `column.id` – dependent.
* `notes`: ghi chú.

