Tài liệu Yêu cầu Hệ thống: AI Database Design Assistant (LangGraph)
1. Tổng quan hệ thống
Xây dựng một tác nhân AI (AI Agent) có khả năng hiểu yêu cầu ngôn ngữ tự nhiên để thiết kế, chỉnh sửa và chuyển đổi các mô hình Cơ sở dữ liệu (Conceptual, Logical, Physical). Hệ thống giao tiếp qua JSON để đồng bộ giữa giao diện (UI Diagram) và logic dữ liệu (Model).

2. Kiến trúc LangGraph (State & Nodes)
Hệ thống sẽ được xây dựng dựa trên một StateGraph để quản lý trạng thái thiết kế hiện tại.

State Definition
schema_model: Đối tượng JSON chứa cấu trúc DB (tables, fields, relationships).

ui_diagram: Đối tượng JSON chứa thông tin tọa độ, style để hiển thị.

history: Danh sách các phiên bản schema để hỗ trợ tính năng Revert.

current_level: Enum [Conceptual, Logical, Physical].

user_input: Yêu cầu mới nhất từ người dùng.

Các Nodes chính
Requirement_Parser: Phân tích yêu cầu từ ngôn ngữ tự nhiên.

Schema_Generator: Tạo mới hoặc cập nhật schema_model và ui_diagram.

Schema_Converter: Thực hiện chuyển đổi giữa các cấp độ (ví dụ: Từ Logical sang Physical bằng cách thêm Data Types, Constraints).

Validator: Kiểm tra tính hợp lệ của Schema (Primary Key, Foreign Key integrity).

Router: Điều hướng dựa trên ý định người dùng (Tạo mới, Chỉnh sửa, Chuyển đổi hay Revert).

3. Chức năng chi tiết & Workflow
3.1. Tạo Schema từ Ngôn ngữ tự nhiên
Input: "Xây dựng DB cho hệ thống bán hàng điện tử có quản lý kho và voucher."

AI Action: Trích xuất các thực thể, thuộc tính và mối quan hệ.

Output: Cập nhật đồng thời file model.json và tự động tính toán tọa độ cho file diagram.json.

3.2. Chatbot chỉnh sửa (Iterative Editing)
Input: "Thêm trường ngày sinh vào bảng Users" hoặc "Xóa quan hệ giữa bảng A và B".

AI Action: * Đọc schema_model hiện tại từ State.

Thực hiện thay đổi cục bộ (diff) để giữ nguyên các phần khác.

Cập nhật ui_diagram (giữ nguyên vị trí các bảng cũ, chỉ thêm/bớt node/edge tương ứng).

3.3. Chuyển đổi & Revert (Convert/Revert)
Conversion Logic:

Conceptual -> Logical: Phân rã quan hệ n-n thành bảng trung gian, xác định Foreign Keys.

Logical -> Physical: Áp dụng kiểu dữ liệu cụ thể (PostgreSQL, MySQL,...) và các index.

Revert Logic: Sử dụng một Node quản lý history trong LangGraph để khôi phục lại State của bước trước đó.

4. Đặc tả dữ liệu (Data Contract)
AI cần tuân thủ cấu trúc file bạn đã định nghĩa:

File Model (model.json): Chứa cấu trúc logic (Entities, Attributes, Relationships, Constraints).

File Diagram (diagram.json): Chứa metadata cho UI (Node positions, Edge paths, Zoom level).

Lưu ý cho AI: Khi cập nhật model.json, phải đảm bảo diagram.json được cập nhật tương ứng để tránh tình trạng lệch pha giữa dữ liệu và hiển thị.