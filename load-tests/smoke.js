import http from "k6/http";
import { check, sleep } from "k6";

export const options = { vus: 1, duration: "1m" };
const baseUrl = __ENV.BASE_URL || "http://127.0.0.1:8000";

export default function () {
  check(http.get(`${baseUrl}/api/v1/recommendations/health`), { "health 200": (r) => r.status === 200 });
  check(http.get(`${baseUrl}/api/v1/clubs`), { "clubs 200": (r) => r.status === 200 });
  const params = { headers: { "Content-Type": "application/json" } };
  check(
    http.post(`${baseUrl}/api/v1/recommendations`, JSON.stringify({ query: "영상 편집을 배우고 싶어", top_k: 5 }), params),
    { "recommendation 200": (r) => r.status === 200 },
  );
  sleep(1);
}
