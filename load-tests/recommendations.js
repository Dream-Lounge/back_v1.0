import http from "k6/http";
import { check } from "k6";

export const options = {
  stages: [
    { duration: "2m", target: 10 },
    { duration: "5m", target: 25 },
    { duration: "5m", target: 50 },
    { duration: "5m", target: 100 },
    { duration: "2m", target: 0 },
  ],
  thresholds: {
    http_req_failed: ["rate<0.005"],
    "http_req_duration{endpoint:recommend}": ["p(95)<500", "p(99)<1000"],
  },
};

const baseUrl = __ENV.BASE_URL || "http://127.0.0.1:8000";
const queries = ["영상 편집", "초보 개발 프로젝트", "주말 봉사", "밴드 공연", "친목 동아리"];

export default function () {
  const query = queries[__ITER % queries.length];
  const response = http.post(
    `${baseUrl}/api/v1/recommendations`,
    JSON.stringify({ query, top_k: 5 }),
    { headers: { "Content-Type": "application/json" }, tags: { endpoint: "recommend" } },
  );
  check(response, { "status 200": (r) => r.status === 200 });
}
