# EcoRouter-LLM — Roadmap MVP

**Obiettivo.** Consegnare in 32 ore una demo backend stabile e riproducibile che mostri come EcoRouter-LLM seleziona un modello, gestisce il fallimento di un provider e rende verificabile il costo di ogni tentativo.

**Baseline.** Commit `db71d8860ffdc9bd387541c28d83985629ff7c53`. Lo snapshot esaminato contiene lo scaffold Python, i confini iniziali dei package e i test di import. Le funzionalità applicative sono da implementare. Il tag `v0.1.0` è riportato nella roadmap precedente e va verificato nel repository.

**Target di release.** Demo locale production-oriented, avviabile con Docker Compose e verificabile tramite una pipeline Jenkins eseguita. La decisione di release spetta all’Engineering Lead.

## 1. Scenario da dimostrare

1. Avviare API e PostgreSQL da un checkout pulito usando il runbook.
2. Inviare una richiesta autenticata a `POST /v1/inference`.
3. Mostrare che un modello con score favorevole viene escluso quando viola un hard constraint, compresa la soglia minima di qualità.
4. Simulare un errore recuperabile del primo provider. Mostrare un fallback consentito e, con una seconda richiesta, un fallback negato per budget o deadline residui.
5. Consultare `GET /v1/analytics/summary` per osservare token, costi per tentativo e savings controfattuali sulle richieste comparabili.
6. Verificare che una seconda identità tenant veda soltanto i propri dati.
7. Collegare richiesta, tentativi e risultato tramite correlation ID, log strutturati e metriche.

I profili modello, il pricing e le risposte dei provider in demo mode sono deterministici. L’avvio e lo scenario demo richiedono credenziali locali per le API e funzionano senza credenziali di provider LLM esterni.

## 2. Scope e decisioni da approvare

| Area | Obbligatorio per la demo | Dopo la demo o su approvazione |
|---|---|---|
| Routing | Catalogo statico, almeno due candidati, hard constraints, qualità minima, scoring e tie-break deterministico | Calibrazione con dataset, catalogo dinamico e scoring adattivo |
| Resilience | Timeout cumulativo, classificazione degli errori e al massimo due chiamate per richiesta, inclusi retry e fallback. Il profilo demo usa al massimo un fallback | Retry sullo stesso provider, backoff e circuit breaker verificato |
| Provider | Adapter mock asincroni con successo, errore recuperabile e timeout controllati | Groq live e relativo smoke test |
| Persistence | PostgreSQL, una migrazione, ledger dei tentativi e aggregazione per tenant | Repository amministrativi, catalogo prezzi dinamico e riconciliazione con fatture provider |
| API e sicurezza | Inference, analytics, health e readiness. API key associate lato server al tenant, limiti sulle richieste e isolamento verificato | API OpenAI-compatible, SSO/OIDC, RBAC avanzato e rate limiting distribuito |
| Observability | Log JSON, correlation ID, contatori e istogrammi Prometheus | Grafana, tracing distribuito, OpenTelemetry Collector, Loki e Tempo |
| Agentic AI | Contratto applicativo riusabile per l’inferenza | Workflow LangGraph solo con una decisione utile, tool autorizzati lato server e limiti espliciti |
| Delivery | Docker Compose, Jenkins, smoke test, scansioni, benchmark e runbook | Deploy automatico in ambienti remoti e scalabilità distribuita |

Entro l’ora 2, l’Engineering Lead approva lo scope, le decisioni di dominio che sbloccano il codice e i criteri di performance. Se Groq live, circuit breaker o LangGraph diventano obbligatori, si rivedono stime e perimetro prima di iniziarli. Se il live mode viene rinviato, il README lo riporta come funzionalità fuori scope per questa release.

Dashboard React, Kubernetes e architettura multi-region restano fuori perimetro.

## 3. Sequenza di lavoro

Le stime includono implementazione, verifica QA e revisione. Le EPIC conservano i propri ID e procedono per flussi integrabili. In particolare, il primo endpoint e lo smoke test partono insieme al caso d’uso, mentre il dominio resta indipendente dagli adapter.

| Giorno | Ore | EPIC e lavoro | Evidenza attesa |
|---|---:|---|---|
| 1 | 2 | `EPIC 01` — Domain Specification e decisioni architetturali | Invarianti, semantica dei tentativi e criteri di accettazione approvati |
| 1 | 4 | `EPIC 01` — Eligibility, scoring e tie-break | Test unitari su qualità, vincoli e selezione deterministica |
| 1 | 2 | `EPIC 00` / `EPIC 08` — Quality gate, Dockerfile, Compose e Jenkins iniziale | Prima esecuzione Jenkins effettiva sul bootstrap e avvio dello stack minimo |
| 2 | 8 | `EPIC 02` / `EPIC 03` / `EPIC 05` — Inference API autenticata, use case, mock provider e strict fallback | Richiesta via Compose con successo, fallback ammesso e fallback negato |
| 3 | 8 | `EPIC 04` / `EPIC 05` / `EPIC 06` — PostgreSQL, ledger, isolamento tenant e analytics | E2E da inferenza ad analytics, test di isolamento e migrazione ripetibile |
| 4 | 2 | `EPIC 07` — Log strutturati, correlation ID e metriche | Riscontro tra richiesta, tentativi e metriche esposte |
| 4 | 6 | `EPIC 08` — Validazione release, benchmark, scansioni e correzioni | Pipeline candidata, smoke test da checkout pulito e decisione di release |
| **Totale** | **32** | | |

**Checkpoint.** Se all’ora 16 manca il flusso di inferenza via Compose, si sospendono le estensioni e si chiude quel flusso per primo. Se all’ora 24 persistono problemi nel ledger o nell’isolamento tenant, le ore di stabilizzazione vanno a quegli errori prima di aggiungere funzionalità. Eventuali modifiche ai criteri di release richiedono approvazione esplicita dell’Engineering Lead.

## 4. EPIC e criteri di uscita

### EPIC 00 — Engineering Foundation

Lo scaffold è disponibile. Le evidenze di esecuzione della pipeline vanno acquisite.

- [ ] Rendere questa roadmap disponibile insieme alla baseline di review.
- [ ] Usare `make quality` come entry point comune per Ruff, format check, Mypy strict e Pytest.
- [ ] Registrare e fissare le versioni usate in CI per ambiente Python, dipendenze e immagini.
- [ ] Registrare la prima esecuzione Jenkins con SHA e risultati dei gate.

### EPIC 01 — Domain Engineering

- [ ] Approvare una Domain Specification breve con esempi tabellari per i casi limite. Registrare le decisioni significative in ADR.
- [ ] `D01` — Applicare i vincoli obbligatori prima dello scoring. Escludere i candidati per cui mancano i dati necessari a verificare un hard constraint.
- [ ] `D02` — Applicare la qualità minima a ogni candidato. Usare profili statici documentati per la demo e descriverne la provenienza.
- [ ] `D03` — Riapplicare i vincoli al fallback, inclusi disponibilità e budget e deadline residui. Terminare con un errore esplicito quando non esistono candidati idonei.
- [ ] `D04` — Tenere `confidence`, qualità e score distinti. Definire un tie-break stabile a parità di score.
- [ ] Specificare unità, precisione e arrotondamento dei costi, pricing snapshot, lifecycle del tentativo e trattamento della latenza stimata.
- [ ] Testare almeno candidato escluso con score alto, qualità al limite, parità di score, catalogo senza candidati validi e fallback oltre i limiti residui.

Il Domain resta indipendente da FastAPI, PostgreSQL, SDK dei provider e LangGraph.

### EPIC 02 — Application Engineering

- [ ] Implementare `RouteInference` come punto d’ingresso applicativo. Introdurre le porte necessarie al catalogo, ai provider e alla registrazione dei tentativi.
- [ ] Calcolare una sola deadline per richiesta e usare il tempo residuo prima di ogni chiamata. Applicare il budget cumulativo lato server.
- [ ] Definire cosa riservare prima della chiamata, quando rilasciare la riserva e quando fermare il fallback se un tentativo con usage sconosciuto impedisce di stimare il budget residuo in sicurezza.
- [ ] Verificare successo, esaurimento dei candidati, timeout cumulativo, cancellazione e fallimento della registrazione. Documentare il recupero quando il provider ha risposto e il ledger non è disponibile.

### EPIC 03 — AI & Provider Adapters

- [ ] Implementare adapter mock asincroni con esiti e usage riproducibili.
- [ ] Distinguere errori recuperabili, errori definitivi e timeout con usage potenzialmente sconosciuto.
- [ ] Verificare che gli adapter rispettino i limiti ricevuti e che ogni chiamata effettiva conti nel limite complessivo dei tentativi.
- [ ] Se Groq viene approvato, eseguire uno smoke test separato dalla suite deterministica e registrare configurazione ed esito.

### EPIC 04 — Persistence & Transaction Management

- [ ] Avviare PostgreSQL via Compose e applicare una migrazione ripetibile.
- [ ] Registrare per tentativo tenant, identificativo, esito, usage, stato del costo e pricing snapshot. Impedire scritture duplicate dello stesso tentativo con un vincolo univoco e una scrittura idempotente.
- [ ] Applicare il filtro tenant a ogni lettura applicativa. Testare duplicati, errore di persistenza e isolamento su PostgreSQL reale.
- [ ] Dichiarare separatamente la semantica delle richieste HTTP duplicate. L’idempotenza del ledger copre la registrazione dei tentativi.

### EPIC 05 — API & Security

- [ ] Esporre `POST /v1/inference`, `GET /v1/analytics/summary`, `GET /healthz` e `GET /readyz`.
- [ ] Derivare il tenant dall’identità autenticata lato server. Validare dimensione del payload, token richiesti e intervallo delle query analytics.
- [ ] Applicare un limite di concorrenza e una quota per tenant coerenti con il deployment demo. Documentare il perimetro di validità dei limiti.
- [ ] Verificare credenziali mancanti e non valide, isolamento tra due tenant, richieste oltre i limiti e indisponibilità del database.
- [ ] Tenere segreti, prompt e risposte fuori dai log. Esporre metriche e diagnostica soltanto sulla rete locale o interna prevista dalla configurazione demo.

### EPIC 06 — Cost Management & Business Analytics

- [ ] Calcolare in `Decimal` il costo da token riportati e pricing snapshot. Conservare valori stimati e valori calcolati da usage noto come categorie distinte.
- [ ] Registrare i tentativi falliti e i fallback. Rappresentare usage e costo sconosciuti esplicitamente.
- [ ] Per una richiesta completata e comparabile, calcolare il costo baseline applicando il pricing di riferimento agli stessi token della risposta completata. Sottrarre la somma dei costi di tutti i tentativi per ottenere il risparmio netto.
- [ ] Escludere dal calcolo dei savings le richieste con tentativi a costo sconosciuto e mostrare il conteggio delle esclusioni. Conservare eventuali risparmi negativi.
- [ ] Etichettare i risultati della demo come simulati e la baseline come controfattuale. Verificare il totale analytics contro il ledger con un dataset deterministico.

### EPIC 07 — Observability & Security Monitoring

- [ ] Propagare il correlation ID tra API, use case e adapter. Verificare il collegamento tra una richiesta e i suoi tentativi.
- [ ] Esporre contatori per richieste, errori e fallback e un istogramma di latenza. Usare label a cardinalità limitata e tenere request ID e tenant ID fuori dalle label.
- [ ] Verificare che log e risposte d’errore escludano API key, prompt, output e dettagli sensibili dei provider.

### EPIC 08 — Docker Compose, Jenkins & Release

- [ ] Verificare installazione, avvio dello stack, migrazione, readiness, smoke test e riavvio seguendo il runbook da un checkout pulito.
- [ ] Eseguire Jenkins sul commit candidato con quality gate, test di integrazione ed E2E, scansioni di segreti, dipendenze e immagini, build e smoke test Compose. Verificare che un gate obbligatorio fallito impedisca di promuovere il candidato.
- [ ] Conservare SHA, esiti dei test, coverage, scansioni, benchmark e identificativo dell’immagine del candidato.
- [ ] Aggiornare README e runbook con avvio, verifica, arresto, reset della demo, troubleshooting e limiti operativi.
- [ ] Creare il tag `v1.0.0-demo` dopo l’approvazione dell’Engineering Lead.

## 5. QA e performance acceptance criteria

La chat di implementazione consegna commit, diff e criteri di accettazione. La chat QA indipendente verifica il comportamento su quella revisione, scrive i test di regressione e associa i report allo SHA. La review usa la stessa baseline di codice, test e report.

- **Unit** — Invarianti del dominio, limiti cumulativi dei tentativi, formule di costo e dati mancanti.
- **Integration** — API con provider controllati, PostgreSQL, migrazione, idempotenza del ledger e isolamento tenant.
- **E2E** — Successo, strict fallback, fallimento esplicito a limiti esauriti e riconciliazione tra tentativi e analytics.
- **Coverage** — Pubblicare la branch coverage. Il target iniziale dell’85% resta indicativo. La chiusura richiede test espliciti sulle invarianti critiche.

### Benchmark demo da approvare all’ora 2

Eseguire 20 richieste di warm-up e poi 200 richieste con concorrenza 10, usando API e PostgreSQL via Compose e un provider mock a ritardo configurabile. Registrare SHA, macchina, configurazione, throughput, error rate e latenza end-to-end p50/p95/p99. Misurare anche il tempo trascorso negli adapter per ogni tentativo e riportare l’overhead di orchestrazione separatamente.

| Scenario | Soglia proposta |
|---|---|
| Successo con mock senza ritardo | p95 end-to-end ≤ 150 ms e zero errori inattesi sulle 200 richieste |
| Deadline esaurita con mock lento | Errore esplicito, nessun nuovo tentativo dopo la deadline e risposta entro deadline più 100 ms nel profilo di carico concordato |
| Carico superiore al limite configurato | Rifiuto controllato delle richieste in eccesso e ripresa del servizio al rientro nel limite |

Le soglie descrivono il profilo locale documentato. Il report riporta gli esiti misurati e gli scostamenti.

## 6. Definition of Done — Release demo

- [ ] Scenario dimostrativo ripetibile da checkout pulito via Docker Compose.
- [ ] Invarianti di routing, limiti dei tentativi, isolamento tenant e riconciliazione dei costi verificati dalla QA.
- [ ] Jenkins eseguito sul commit candidato e report disponibili per test, coverage, scansioni e performance.
- [ ] Criteri di performance approvati e verificati. Eventuali scostamenti hanno una decisione esplicita dell’Engineering Lead.
- [ ] Log, correlation ID e metriche osservabili durante lo smoke test.
- [ ] Zero blocker aperti e zero rischi di sicurezza Critical o High privi di mitigazione verificata.
- [ ] README e runbook riproducibili. Modalità live ed estensioni rinviate documentate.
- [ ] Engineering Lead approva il commit candidato e autorizza il tag di release.