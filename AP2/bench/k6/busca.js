// Teste de carga da busca (k6). Mede a latencia de GET /questoes em quatro cenarios, em sequencia:
//   sem_cache : cada requisicao ignora o cache (Cache-Control: no-cache) e vai ao Elasticsearch
//   com_cache : 30 consultas fixas, cache aquecido no setup (quase 100% de acertos)
//   misto     : 80% de consultas populares (acertam o cache) e 20% aleatorias (erram)
//   estresse  : rampa de 5 a 60 usuarios virtuais, sem cache, para achar o ponto de saturacao
// Uso: ver bench/rodar_carga.ps1
import http from "k6/http";
import { check } from "k6";

const BASE = __ENV.BASE || "http://api:8000";
const TERMOS = ["ética", "sustentabilidade", "desigualdade social", "banco de dados", "saúde pública",
  "direitos humanos", "tecnologia", "educação", "violência", "meio ambiente", "inteligência artificial",
  "democracia", "trabalho", "cidadania", "engenharia", "paciente", "contrato", "algoritmo", "gestão",
  "política pública", "cultura", "diversidade", "energia", "comunicação", "segurança", "privacidade",
  "inclusão", "responsabilidade", "pesquisa", "qualidade"];
const ANOS = [2018, 2019, 2021, 2022, 2023];
const pick = a => a[Math.floor(Math.random() * a.length)];

function consultaAleatoria() {
  let p = "q=" + encodeURIComponent(pick(TERMOS));
  if (Math.random() < 0.5) p += "&ano=" + pick(ANOS);
  if (Math.random() < 0.3) p += "&componente=" + pick(["FG", "CE"]);
  if (Math.random() < 0.2) p += "&tipo_questao=" + pick(["objetiva", "discursiva"]);
  return p + "&pagina=" + (1 + Math.floor(Math.random() * 3)) + "&tamanho=10";
}
// 30 consultas fixas (uma por termo) para o cenario com cache
const FIXAS = TERMOS.map(t => "q=" + encodeURIComponent(t) + "&pagina=1&tamanho=10");

export const options = {
  scenarios: {
    sem_cache: { executor: "constant-vus", vus: 10, duration: "60s", exec: "semCache", startTime: "0s" },
    com_cache: { executor: "constant-vus", vus: 10, duration: "60s", exec: "comCache", startTime: "70s" },
    misto: { executor: "constant-vus", vus: 10, duration: "60s", exec: "misto", startTime: "140s" },
    estresse: {
      executor: "ramping-vus", exec: "semCache", startTime: "210s", startVUs: 5,
      stages: [{ duration: "30s", target: 20 }, { duration: "30s", target: 40 }, { duration: "30s", target: 60 }, { duration: "30s", target: 60 }],
    },
  },
  thresholds: {
    "http_req_duration{scenario:sem_cache}": ["p(95)<500"],
    "http_req_duration{scenario:com_cache}": ["p(95)<50"],
    "http_req_duration{scenario:misto}": ["p(95)<500"],
    "http_req_duration{scenario:estresse}": ["p(95)<2000"],
    http_req_failed: ["rate<0.01"],
  },
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
};

export function setup() {
  const r = http.post(`${BASE}/auth/token`, { username: __ENV.USUARIO || "professor1", password: __ENV.SENHA });
  if (r.status !== 200) throw new Error("login falhou: " + r.status);
  const token = r.json("access_token");
  const h = { headers: { Authorization: "Bearer " + token } };
  http.post(`${BASE}/cache/invalidar`, null, h);
  for (const q of FIXAS) http.get(`${BASE}/questoes?${q}`, h);          // aquece o cache do cenario com_cache
  for (const t of TERMOS.slice(0, 10)) http.get(`${BASE}/questoes?q=${encodeURIComponent(t)}&pagina=1&tamanho=10`, h);
  return { token };
}

function buscar(data, query, semCache) {
  const headers = { Authorization: "Bearer " + data.token };
  if (semCache) headers["Cache-Control"] = "no-cache";
  const r = http.get(`${BASE}/questoes?${query}`, { headers });
  check(r, { "status 200": x => x.status === 200 });
}
export function semCache(data) { buscar(data, consultaAleatoria(), true); }
export function comCache(data) { buscar(data, pick(FIXAS), false); }
export function misto(data) {
  if (Math.random() < 0.8) buscar(data, pick(FIXAS.slice(0, 10)), false);
  else buscar(data, consultaAleatoria(), false);
}

export function handleSummary(data) {
  // RODADA identifica a repeticao (k6-resumo-r1.json, r2, r3); sem ela grava k6-resumo.json
  const nome = __ENV.RODADA ? `k6-resumo-r${__ENV.RODADA}.json` : "k6-resumo.json";
  return { [`/bench/resultados/${nome}`]: JSON.stringify(data, null, 2), stdout: `\nResumo salvo em bench/resultados/${nome}\n` };
}
