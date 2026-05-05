# Reflection — Lab 19

**Tên:** _Nguyễn Phan Tuấn Anh_
**Cohort:** _A20-K2_
**Path đã chạy:** _docker_

---

## Câu hỏi (≤ 200 chữ)

> Trên golden set 50 queries, mode nào thắng ở loại query nào (`exact` /
> `paraphrase` / `mixed`), và tại sao? Khi nào bạn **không** dùng hybrid
> (i.e. khi nào pure BM25 hoặc pure vector là lựa chọn đúng)?

**Kết quả Precision@10:**

| Loại query | n   | BM25  | Semantic | Hybrid |
|------------|-----|-------|----------|--------|
| exact      | 15  | 96.7% | 88.7%   | 96.7%  |
| paraphrase | 15  | 33.3% | 24.0%   | 32.0%  |
| mixed      | 20  | 97.0% | 98.5%   | **100%** |
| **avg**    | 50  | 77.8% | 73.2%   | **78.6%** |

**Phân tích:**

- **`exact`**: BM25 thắng gần ngang hybrid (96.7% vs 96.7%). Query chứa từ kỹ thuật verbatim trong corpus — BM25 đã đủ signal mạnh, hybrid không cải thiện thêm.

- **`paraphrase`**: Cả ba đều thất bại nặng (24–33%). Đây là corpus Việt Nam + embedding model `bge-small-en` (English-trained) — semantic recall trên paraphrase tiếng Việt rất yếu. Hybrid chỉ marginally tốt hơn BM25 nhưng vẫn thấp. Đổi sang `bge-m3` (multilingual) sẽ cải thiện đáng kể.

- **`mixed`**: Hybrid thắng tuyệt đối (100%) — query có cả từ exact lẫn ý tưởng paraphrased, cả hai signal bổ trợ nhau qua RRF.

**Hybrid không dùng khi:** (1) **Latency cứng** — hybrid P99 ~116ms vs keyword 24.6ms; nếu rubric P99 < 50ms thì hybrid không đạt. (2) **Query paraphrase thuần túy** — cả hybrid lẫn semantic đều kém trên corpus không match embedding model. (3) **Query exact đơn giản** — BM25 thắng ngang hybrid mà nhanh hơn 4-5×.

---

## Điều ngạc nhiên nhất khi làm lab này

Điều bất ngờ nhất là hybrid search thắng trên **trung bình** nhưng **không thắng trên tất cả** các loại query — `exact` queries BM25 ngang hybrid, `paraphrase` thì cả ba đều thất bại nặng. Điều này phá vỡ myth "hybrid luôn thắng" và cho thấy embedding model phải match ngôn ngữ corpus mới phát huy tác dụng. Thứ hai bất ngờ là Feast đạt P99 < 10ms với SQLite local mà không cần Redis — offline store benchmark rất dễ setup đúng.

---

## Bonus challenge

- [x] Đã làm bonus (xem `bonus/`)
- [ ] Pair work với: _None_
