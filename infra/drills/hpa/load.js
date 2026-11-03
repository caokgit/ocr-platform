// k6 load for the HPA drill: ramps to 40 virtual users on podinfo through the Gateway, holds, then stops.
import http from 'k6/http';
import { check } from 'k6';

export const options = {
  // The Gateway's load balancer is published on a localhost port (WSL with Docker Desktop).
  hosts: { 'podinfo.lab.internal': '127.0.0.1' },
  stages: [
    { duration: '30s', target: 40 },
    { duration: '3m', target: 40 },
    { duration: '10s', target: 0 },
  ],
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
  },
};

const url = `https://podinfo.lab.internal:${__ENV.PORT}/`;

export default function () {
  const res = http.get(url, { headers: { Host: 'podinfo.lab.internal' } });
  check(res, { 'status 200': (r) => r.status === 200 });
}
