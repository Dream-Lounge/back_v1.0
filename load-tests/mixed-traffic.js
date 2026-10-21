import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  vus: 50,
  duration: "15m",
  thresholds: {
    http_req_failed: ["rate<0.005"],
    http_req_duration: ["p(95)<700"],
  },
};

const baseUrl = __ENV.BASE_URL || "http://127.0.0.1:8000";

export default function () {
  const slot = __ITER % 10;
  let response;
  if (slot < 6) {
    response = http.get(`${baseUrl}/api/v1/clubs`, { tags: { endpoint: "clubs" } });
  } else if (slot < 8) {
    response = http.get(`${baseUrl}/api/v1/recommendations/health`, { tags: { endpoint: "health" } });
  } else {
    response = http.post(
      `${baseUrl}/api/v1/recommendations`,
      JSON.stringify({ query: "초보도 가능한 프로젝트 동아리", top_k: 5 }),
      { headers: { "Content-Type": "application/json" }, tags: { endpoint: "recommend" } },
    );
  }
  check(response, { "status 200": (r) => r.status === 200 });
  sleep(0.5);
}
