import type { DataSource } from "../types";
import { apiDataSource } from "./api";
import { mockDataSource } from "./mock";

// Chọn nguồn dữ liệu bằng VITE_DATA_SOURCE=mock|api (mặc định api khi build cho VPS)
export const dataSource: DataSource = import.meta.env.VITE_DATA_SOURCE === "mock" ? mockDataSource : apiDataSource;
