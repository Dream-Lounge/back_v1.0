import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  vus: 25,
  duration: "2h",
  thresholds: {
    http_req_failed: ["rate<0.001"],
    http_req_duration: ["p(95)<700"],
  },
};

const baseUrl = __ENV.BASE_URL || "http://127.0.0.1:8000";
const queries = ["사진", "공연", "봉사", "개발 프로젝트", "친목"];

export default function () {
  const response = http.post(
    `${baseUrl}/api/v1/recommendations`,
    JSON.stringify({ query: queries[__ITER % queries.length], top_k: 5 }),
    { headers: { "Content-Type": "application/json" } },
  );
  check(response, { "status 200": (r) => r.status === 200 });
  sleep(1);
}
