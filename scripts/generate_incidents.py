#!/usr/bin/env python3
"""Generate a realistic synthetic incident dataset for RecallSRE.

Produces backend/data/incidents.json — ~28 fully-detailed production incidents
across 9 services, with recurring archetypes so the memory demo can show
genuine "similar incident" matches.

Each incident follows the schema the agent's memory layer uses:
  id, title, service, severity, started_at, resolved_at, error_signature,
  symptoms, logs_snippet, deployment, git_commit, root_cause,
  investigation_steps, commands_used, fix, engineer, mttr_minutes, outcome
"""
import json
import random
from datetime import datetime, timedelta

random.seed(42)

ENGINEERS = [
    "Priya Sharma", "Arjun Mehta", "Rahul Verma", "Sarah Chen",
    "David Kim", "Ananya Iyer", "Vikram Singh", "Emily Zhang",
    "Karthik Rao", "Meera Nair",
]

SERVICES = [
    "payment-service", "auth-service", "order-service",
    "notification-service", "search-service", "user-service",
    "inventory-service", "billing-service", "api-gateway",
]

# Each archetype: (name, error_signature, root_cause_template, fix_template,
#                  log_template, investigation_steps, commands)
ARCHETYPES = [
    {
        "name": "db_pool_exhaustion",
        "title": "{service} DB connection pool exhaustion",
        "severity": "critical",
        "error_signature": "HTTP 500 spike + 'remaining connection slots are reserved' in postgres logs",
        "symptoms": [
            "p99 latency jumped from 180ms to 8.2s",
            "error rate 38% on /api/v1/{short}/charge",
            "postgres logs: 'remaining connection slots are reserved for non-replication superuser connections'",
            "application logs: HikariPool - Connection is not available, request timed out after 30000ms",
        ],
        "log_snippet": (
            "{ts} ERROR [HikariPool-1 housekeeper] com.zaxxer.hikari.pool.HikariPool - "
            "HikariPool-1 - Connection is not available, request timed out after 30000ms.\n"
            "{ts} ERROR [http-nio-8080-exec-214] c.e.{svc}.PaymentController - "
            "charge failed: org.postgresql.util.PSQLException: FATAL: remaining connection slots "
            "are reserved for non-replication superuser connections\n"
            "{ts} WARN  [HikariPool-1 housekeeper] com.zaxxer.hikari.pool.HikariPool - "
            "HikariPool-1 - Thread starvation or clock leap detected (housekeeper delta=42s)."
        ),
        "root_cause": "Database connection pool exhaustion: pool maxed at {pool_old} connections after {deploy} increased per-request query fan-out; connections leaked on timeout paths and were never returned.",
        "fix": "Increased HikariCP maximumPoolSize from {pool_old} to {pool_new}, added leakDetectionThreshold=60s, and rolled back {deploy} until the N+1 query regression was patched.",
        "investigation": [
            "Checked Grafana: pg_stat_activity showed {pool_old}/{pool_old} connections in 'idle in transaction'",
            "Correlated spike start with deployment {deploy} 18 minutes earlier",
            "Confirmed leak via heap dump: 4,100 abandoned PgConnection objects",
            "Verified fix on staging with 2x load test before prod rollout",
        ],
        "commands": [
            "kubectl logs -l app={svc} --since=30m | grep -i 'connection is not available' | head -20",
            "kubectl exec -it postgres-0 -- psql -c \"select count(*), state from pg_stat_activity group by state;\"",
            "kubectl rollout history deployment/{svc}",
            "kubectl set env deployment/{svc} SPRING_DATASOURCE_HIKARI_MAXIMUM_POOL_SIZE={pool_new}",
        ],
        "mttr": (3, 9),
    },
    {
        "name": "bad_deploy_rollback",
        "title": "Regression after {deploy} deploy on {service}",
        "severity": "critical",
        "error_signature": "HTTP 500 spike starting within minutes of deployment {deploy}",
        "symptoms": [
            "error rate 0.2% → 24% within 4 minutes of deploy",
            "new exception type in logs: NullPointerException in {cls}",
            "canary analysis flagged but auto-promotion was disabled",
            "only pods running {deploy} affected; old revision healthy",
        ],
        "log_snippet": (
            "{ts} ERROR [http-nio-8080-exec-96] c.e.{svc}.{cls} - Unhandled exception processing request\n"
            "java.lang.NullPointerException: Cannot invoke \"String.length()\" because \"token\" is null\n"
            "\tat c.e.{svc}.{cls}.validate({cls}.java:142)\n"
            "\tat c.e.{svc}.{cls}.handle({cls}.java:88)\n"
            "{ts} INFO  [k8s] deployment/{svc} scaled UP replica set {svc}-{deploy} to 12"
        ),
        "root_cause": "Deployment {deploy} shipped a regression: {cls}.validate() dereferences a nullable auth token. The null case was introduced when the token-refresh flow was refactored in commit {commit}.",
        "fix": "Immediate rollback to previous revision via kubectl rollout undo; followed by a hotfix adding null-guard + regression test, redeployed as {deploy_next}.",
        "investigation": [
            "Noticed error spike aligned exactly with deploy timestamp in ArgoCD",
            "Diffed {deploy} vs previous: 14 files changed, token-refresh refactor stood out",
            "Reproduced NPE locally with missing-token request fixture",
            "Rolled back first, root-caused second (incident protocol)",
        ],
        "commands": [
            "kubectl rollout history deployment/{svc}",
            "kubectl rollout undo deployment/{svc} --to-revision={prev_rev}",
            "git log --oneline v{prev_v}..v{cur_v} -- {svc}/",
            "kubectl rollout status deployment/{svc} --watch",
        ],
        "mttr": (6, 18),
    },
    {
        "name": "redis_leak",
        "title": "Redis connection leak in {service}",
        "severity": "high",
        "error_signature": "redis.clients.jedis.exceptions.JedisConnectionException: Could not get a resource from the pool",
        "symptoms": [
            "cache hit rate collapsed 96% → 11%",
            "p95 latency 240ms → 3.1s as traffic fell through to DB",
            "Jedis pool exhausted: 500/500 connections borrowed, 0 idle",
            "DB CPU spiked to 92% from cache-miss thundering herd",
        ],
        "log_snippet": (
            "{ts} ERROR [lettuce-nioEventLoop-4-7] c.e.{svc}.CacheService - cache get failed\n"
            "redis.clients.jedis.exceptions.JedisConnectionException: Could not get a resource from the pool\n"
            "\tat redis.clients.jedis.util.Pool.getResource(Pool.java:59)\n"
            "Caused by: java.util.NoSuchElementException: Timeout waiting for idle object\n"
            "{ts} WARN  [HikariPool-1] connection borrow wait exceeded 5s (cache fallback path)"
        ),
        "root_cause": "Redis connection leak: the async cache-write path borrowed Jedis connections without try-with-resources; under retry storms connections were never returned and the 500-connection pool drained over ~40 minutes.",
        "fix": "Restarted {service} pods to reclaim connections, then shipped a patch wrapping all Jedis borrows in try-with-resources and added pool-exhaustion alerting at 80%.",
        "investigation": [
            "Grafana: jedis_pool_active climbing monotonically since 09:10, never dropping",
            "Heap dump: 500 Jedis objects retained by CompletableFuture callbacks",
            "Code search found 3 borrow sites missing close(); 1 in retry path",
            "Decided restart-then-patch to stop the bleeding immediately",
        ],
        "commands": [
            "redis-cli -h {svc}-redis info clients | grep connected_clients",
            "kubectl top pods -l app={svc}",
            "kubectl rollout restart deployment/{svc}",
            "grep -rn 'getResource()' {svc}/src/main/java --include=*.java",
        ],
        "mttr": (12, 35),
    },
    {
        "name": "oom_kill",
        "title": "{service} pods OOMKilled under load",
        "severity": "high",
        "error_signature": "Kubernetes OOMKilled (exit 137) cascading across {service} pods",
        "symptoms": [
            "pods restarting in a loop: 14 restarts in 20 minutes",
            "kubectl describe pod shows 'Last State: Terminated, Reason: OOMKilled, Exit Code: 137'",
            "heap usage climbing 200MB/min with no plateau",
            "GC pause time p99 hit 4.2s before each kill",
        ],
        "log_snippet": (
            "{ts} WARN  [k8s] pod/{svc}-7d9f8c6b9-x4k2p OOMKilled (exit 137), restarting\n"
            "{ts} ERROR [http-nio-8080-exec-31] c.e.{svc}.ReportService - request failed mid-stream\n"
            "java.lang.OutOfMemoryError: Java heap space\n"
            "\tat java.base/java.util.Arrays.copyOf(Arrays.java:3537)\n"
            "\tat c.e.{svc}.ReportService.buildCsv(ReportService.java:201)"
        ),
        "root_cause": "Memory leak in CSV export path: buildCsv() materialized the full result set in memory instead of streaming. A large enterprise export ({rows} rows) blew the 2Gi heap limit.",
        "fix": "Raised memory limit 2Gi → 4Gi as immediate relief, then rewrote the export to stream rows via cursor pagination; added heap-growth alert.",
        "investigation": [
            "kubectl describe pod confirmed OOMKilled, not crashloop from bad image",
            "Heap dump analyzed with MAT: 1.6GB retained by ArrayList in buildCsv",
            "Found the offending commit: pagination removed 'for performance' in {deploy}",
            "Load-tested streaming fix with 2x largest export before rollout",
        ],
        "commands": [
            "kubectl describe pod -l app={svc} | grep -A3 'Last State'",
            "kubectl exec -it {svc}-0 -- jmap -dump:format=b,file=/tmp/heap.hprof 1",
            "kubectl set resources deployment/{svc} --limits=memory=4Gi",
            "git log --oneline -5 -- {svc}/src/main/java/**/ReportService.java",
        ],
        "mttr": (20, 55),
    },
    {
        "name": "third_party_timeout",
        "title": "{service} cascading timeouts from {vendor} API",
        "severity": "high",
        "error_signature": "Downstream {vendor} API p99 > 10s causing thread-pool saturation",
        "symptoms": [
            "{vendor} API latency p99: 800ms → 12s",
            "{service} tomcat threads saturated: 200/200 busy",
            "circuit breaker never tripped (threshold misconfigured at 50% over 10m)",
            "user-facing checkout error rate 17%",
        ],
        "log_snippet": (
            "{ts} ERROR [http-nio-8080-exec-187] c.e.{svc}.{vendor}Client - {vendor} call timed out after 10000ms\n"
            "java.util.concurrent.TimeoutException: {vendor} charge API did not respond\n"
            "\tat c.e.{svc}.{vendor}Client.charge({vendor}Client.java:64)\n"
            "{ts} WARN  [tomcat] All 200 threads busy for 45s; incoming requests queueing"
        ),
        "root_cause": "{vendor} API degradation (their status page confirmed elevated latency 10:15–11:40 UTC). Our client had no bulkhead isolation and a 10s timeout with 3 retries, so each slow call held a tomcat thread and retries amplified the load 3x.",
        "fix": "Cut timeout to 2s, retries to 1 with jittered backoff, enabled circuit breaker (trip at 20% errors over 1m), and added graceful degradation: queue charges for async retry instead of failing checkout.",
        "investigation": [
            "Checked {vendor} status page: confirmed incident on their side",
            "Thread dump: 193/200 threads blocked in {vendor}Client.charge",
            "Realized retries were multiplying the blast radius",
            "Deployed breaker + degraded-mode config via feature flag (no full deploy needed)",
        ],
        "commands": [
            "kubectl exec -it {svc}-0 -- jstack 1 | grep -c '{vendor}Client.charge'",
            "curl -s https://status.{vendor_lc}.com/api/v2/summary.json | jq .",
            "kubectl set env deployment/{svc} {vendor_uc}_TIMEOUT_MS=2000 {vendor_uc}_MAX_RETRIES=1",
        ],
        "mttr": (15, 45),
    },
    {
        "name": "dns_failure",
        "title": "DNS resolution failures in {service}",
        "severity": "critical",
        "error_signature": "java.net.UnknownHostException for internal service hostnames",
        "symptoms": [
            "inter-service calls failing: UnknownHostException: {dep}-service",
            "kube-dns CPU throttled at 100% (limit too low)",
            "only services in eu-west-1b affected; 1a and 1c healthy",
            "external DNS (google.com) still resolving — internal only",
        ],
        "log_snippet": (
            "{ts} ERROR [http-nio-8080-exec-12] c.e.{svc}.OrderClient - call failed\n"
            "java.net.UnknownHostException: {dep}-service: Name or service not known\n"
            "\tat java.base/java.net.Inet6AddressImpl.lookupAllHostAddr(Native Method)\n"
            "{ts} WARN  [kube-dns] CPU throttling: 100% of 500m limit, query queue backing up"
        ),
        "root_cause": "kube-dns autoscaler misconfigured after cluster upgrade: it scaled on node count, not query rate. A traffic spike 3x'd DNS queries in eu-west-1b and the 2 CoreDNS replicas CPU-throttled, dropping internal resolutions.",
        "fix": "Scaled CoreDNS 2 → 8 replicas immediately, raised CPU limit 500m → 2000m, and switched the autoscaler to query-rate-based scaling.",
        "investigation": [
            "External DNS worked, internal didn't → pointed at kube-dns, not the app",
            "kubectl top pods -n kube-system showed coredns at 100% CPU (throttled)",
            "Checked autoscaler config: still using default node-based formula post-upgrade",
            "Scaled manually first, fixed autoscaler config second",
        ],
        "commands": [
            "kubectl top pods -n kube-system -l k8s-app=kube-dns",
            "kubectl scale deployment coredns -n kube-system --replicas=8",
            "kubectl logs -n kube-system -l k8s-app=kube-dns --tail=50 | grep -i 'timeout\\|dropped'",
            "dig @{dns_ip} {dep}-service.default.svc.cluster.local",
        ],
        "mttr": (8, 25),
    },
    {
        "name": "disk_full",
        "title": "Disk pressure: {service} log volume full",
        "severity": "medium",
        "error_signature": "No space left on device writing to /var/log/{svc}",
        "symptoms": [
            "pods evicted with 'DiskPressure'",
            "application failing to write logs: IOException: No space left on device",
            "log volume at 100%: 48GB of uncompressed JSON logs",
            "log rotation cron had been failing silently for 6 days",
        ],
        "log_snippet": (
            "{ts} ERROR [logback] Failed to write log event: java.io.IOException: No space left on device\n"
            "\tat java.base/java.io.FileOutputStream.writeBytes(Native Method)\n"
            "{ts} WARN  [k8s] Node node-7f3a DiskPressure: node filesystem usage 96%\n"
            "{ts} INFO  [cron] logrotate: last successful run 6 days ago (exit 1, permission denied)"
        ),
        "root_cause": "Log rotation broke 6 days ago when the logrotate config's postrotate script lost execute permission in {deploy}. Uncompressed JSON logs (debug level left on from a prior incident) filled the 50GB volume.",
        "fix": "Cleared oldest logs manually, fixed logrotate permissions, dropped log level back to INFO, and added a disk-usage alert at 75%.",
        "investigation": [
            "df -h showed /var/log at 100%",
            "Found logrotate failing: postrotate permission denied since {deploy}",
            "Noticed DEBUG level still on — leftover from last week's incident",
            "Cleared + fixed rotation + alert, in that order",
        ],
        "commands": [
            "df -h /var/log && du -sh /var/log/{svc}/* | sort -rh | head",
            "grep -i 'error' /var/log/cron | tail -5",
            "chmod +x /etc/logrotate.d/{svc}-postrotate.sh",
            "kubectl set env deployment/{svc} LOG_LEVEL=INFO",
        ],
        "mttr": (10, 30),
    },
    {
        "name": "cert_expiry",
        "title": "TLS certificate expired for {service}",
        "severity": "critical",
        "error_signature": "SSLHandshakeException: certificate expired; clients rejecting connections",
        "symptoms": [
            "mobile clients failing with CERTIFICATE_VERIFY_FAILED",
            "curl: (60) SSL certificate problem: certificate has expired",
            "cert-manager Certificate resource stuck in 'Not Ready'",
            "ACME challenge failing: ingress annotation removed in {deploy}",
        ],
        "log_snippet": (
            "{ts} ERROR [http-nio-8443-exec-3] TLS handshake failed: certificate expired\n"
            "javax.net.ssl.SSLHandshakeException: PKIX path validation failed: "
            "java.security.cert.CertificateExpiredException: NotAfter: {notafter}\n"
            "{ts} WARN  [cert-manager] Certificate {svc}-tls not ready: challenge solver misconfigured"
        ),
        "root_cause": "TLS certificate expired at {notafter}. Auto-renewal broke because {deploy} removed the cert-manager ingress annotation, so the ACME HTTP-01 challenge could never complete. The 30-day expiry warning alert was routed to a dead Slack channel.",
        "fix": "Manually issued certificate via cert-manager (restored annotation), forced renewal, and re-routed expiry alerts to the active #sre-alerts channel with a 14-day warning.",
        "investigation": [
            "openssl s_client showed NotAfter in the past — expiry confirmed in 30s",
            "cert-manager described: challenge pending, solver misconfigured",
            "git blame: annotation removed 41 days ago in {deploy} ('cleanup')",
            "Found the dead alert route — nobody saw the 30/7/1-day warnings",
        ],
        "commands": [
            "echo | openssl s_client -connect {svc}.example.com:443 2>/dev/null | openssl x509 -noout -dates",
            "kubectl describe certificate {svc}-tls -n prod",
            "kubectl annotate ingress {svc} cert-manager.io/cluster-issuer=letsencrypt-prod --overwrite",
            "kubectl cert-manager renew {svc}-tls -n prod",
        ],
        "mttr": (12, 40),
    },
    {
        "name": "kafka_lag",
        "title": "Kafka consumer lag spike in {service}",
        "severity": "high",
        "error_signature": "Consumer group lag > 500k messages on topic {topic}",
        "symptoms": [
            "consumer lag 2k → 540k messages in 25 minutes",
            "downstream notifications delayed up to 40 minutes",
            "consumer CPU fine, but rebalance storm: 11 rebalances in 10 min",
            "one partition's leader on a broker with a failing disk",
        ],
        "log_snippet": (
            "{ts} WARN  [kafka-consumer-3] org.apache.kafka.clients.consumer - "
            "Rebalance started: group {svc}-consumers, protocol cooperative\n"
            "{ts} ERROR [kafka-consumer-3] CommitFailedException: Offset commit failed — "
            "rebalance in progress\n"
            "{ts} WARN  [broker-2] Disk error on /var/kafka-logs: medium error, 3 bad sectors"
        ),
        "root_cause": "Broker-2's disk started failing, slowing its partitions 20x. The consumer group's cooperative rebalance kept reassigning those partitions, and each rebalance paused consumption — a feedback loop that grew lag exponentially.",
        "fix": "Drained broker-2 (kafka-reassign-partitions), replaced the disk, and set max.poll.interval.ms lower so slow consumers get fenced faster instead of triggering rebalances.",
        "investigation": [
            "Lag concentrated on partitions led by broker-2",
            "Broker-2 dmesg showed disk medium errors",
            "Rebalance storm explained why healthy partitions also lagged",
            "Drained the bad broker; lag recovered in 18 minutes",
        ],
        "commands": [
            "kafka-consumer-groups.sh --bootstrap-server kafka:9092 --group {svc}-consumers --describe",
            "dmesg | grep -i 'I/O error\\|medium error' | tail",
            "kafka-reassign-partitions.sh --execute --reassignment-json-file drain-broker2.json",
            "kubectl logs -l app={svc} --since=1h | grep -c 'Rebalance started'",
        ],
        "mttr": (25, 70),
    },
    {
        "name": "feature_flag",
        "title": "Feature flag misconfiguration broke {service} checkout",
        "severity": "high",
        "error_signature": "100% of checkout requests failing after flag {flag} rollout",
        "symptoms": [
            "checkout success rate 99.1% → 0% at exactly 14:00 UTC",
            "flag {flag} rolled to 100% at 14:00 UTC via LaunchDarkly",
            "code path behind flag calls v2 pricing API that isn't deployed yet",
            "no errors in canary because flag was off for canary cohort",
        ],
        "log_snippet": (
            "{ts} ERROR [http-nio-8080-exec-55] c.e.{svc}.CheckoutService - pricing call failed\n"
            "c.e.{svc}.PricingV2Exception: endpoint /v2/price not found (404)\n"
            "\tat c.e.{svc}.CheckoutService.priceWithV2(CheckoutService.java:117)\n"
            "{ts} INFO  [launchdarkly] flag {flag} evaluated true for 100% of contexts"
        ),
        "root_cause": "Feature flag {flag} was rolled to 100% before the v2 pricing service it depends on was deployed. The flag and the service had separate rollout plans owned by different engineers, and the dependency wasn't encoded anywhere.",
        "fix": "Killed the flag (instant rollback to v1 path, recovery in 90 seconds), then added a deployment-dependency check to the flag rollout runbook.",
        "investigation": [
            "Failure started at exactly 14:00 — checked what changed at 14:00",
            "LaunchDarkly audit log: flag {flag} → 100% at 13:59:48",
            "Code read: flag-true path calls /v2/price which doesn't exist yet",
            "Kill-switch first; process fix second",
        ],
        "commands": [
            "ldcli flags update {flag} --rollout 0  # kill switch",
            "kubectl get deployments -l app=pricing-v2  # not found — confirms dependency missing",
            "git log --oneline --grep='{flag}' -5",
        ],
        "mttr": (4, 12),
    },
]

DEPLOY_VERSIONS = ["v2.4.0", "v2.4.1", "v2.5.0", "v2.6.2", "v2.7.0", "v2.8.1", "v3.0.0", "v3.1.2"]
CLASSES = ["AuthFilter", "PaymentValidator", "OrderHandler", "TokenService", "CheckoutFlow"]
VENDORS = [("Stripe", "stripe", "STRIPE"), ("SendGrid", "sendgrid", "SENDGRID"), ("Twilio", "twilio", "TWILIO")]
FLAGS = ["checkout-v2-pricing", "new-recommendations", "fraud-check-v3", "express-checkout"]
TOPICS = ["order.events", "payment.webhooks", "notify.dispatch", "user.activity"]


def ts(base, minutes=0):
    return (base + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pick_archetype_counts():
    # Recurring archetypes get multiple instances so memory matching is demonstrable
    return {
        "db_pool_exhaustion": 4,
        "bad_deploy_rollback": 4,
        "redis_leak": 3,
        "oom_kill": 3,
        "third_party_timeout": 3,
        "dns_failure": 2,
        "disk_full": 2,
        "cert_expiry": 2,
        "kafka_lag": 2,
        "feature_flag": 3,
    }


def main():
    counts = pick_archetype_counts()
    incidents = []
    inc_num = 1
    # Spread incidents over the last ~120 days
    day_cursor = 120
    order = []
    for name, n in counts.items():
        order.extend([name] * n)
    random.shuffle(order)

    for name in order:
        a = next(x for x in ARCHETYPES if x["name"] == name)
        svc = random.choice(SERVICES)
        short = svc.split("-")[0]
        eng = random.choice(ENGINEERS)
        deploy = random.choice(DEPLOY_VERSIONS)
        deploy_next = deploy.replace(deploy.split(".")[-1], str(int(deploy.split(".")[-1]) + 1))
        commit = "".join(random.choices("0123456789abcdef", k=7))
        prev_rev = random.randint(8, 20)

        start = datetime(2026, 5, 30) + timedelta(days=random.randint(0, 118),
                                                  hours=random.randint(0, 23),
                                                  minutes=random.randint(0, 59))
        mttr_lo, mttr_hi = a["mttr"]
        mttr = random.randint(mttr_lo, mttr_hi)
        end = start + timedelta(minutes=mttr)

        fmt = dict(
            service=svc, svc=svc, short=short, deploy=deploy, deploy_next=deploy_next,
            commit=commit, prev_rev=prev_rev, prev_v=deploy,
            cur_v=deploy_next, cls=random.choice(CLASSES),
            ts=ts(start), notafter=ts(start - timedelta(days=1)),
            pool_old=random.choice([50, 100, 100, 200]),
            pool_new=random.choice([250, 300, 500]),
            rows=f"{random.randint(800, 4200)},{random.randint(100,999)}",
            dns_ip=f"10.96.{random.randint(0,255)}.{random.randint(2,254)}",
            dep=random.choice([s for s in SERVICES if s != svc]),
            vendor="Stripe", vendor_lc="stripe", vendor_uc="STRIPE",
            flag="checkout-v2-pricing", topic="order.events",
        )
        if name == "third_party_timeout":
            vendor, vendor_lc, vendor_uc = random.choice(VENDORS)
            fmt.update(vendor=vendor, vendor_lc=vendor_lc, vendor_uc=vendor_uc)
        else:
            fmt.update(vendor="Stripe", vendor_lc="stripe", vendor_uc="STRIPE")
        if name == "feature_flag":
            fmt.update(flag=random.choice(FLAGS))
        else:
            fmt.update(flag="checkout-v2-pricing")
        if name == "kafka_lag":
            fmt.update(topic=random.choice(TOPICS))
        else:
            fmt.update(topic="order.events")

        # avoid KeyError for templates that don't use every key — format safely
        def safe_format(t):
            try:
                return t.format(**fmt)
            except KeyError:
                return t

        incidents.append({
            "id": f"INC-{inc_num:04d}",
            "title": safe_format(a["title"]),
            "service": svc,
            "severity": a["severity"],
            "started_at": ts(start),
            "resolved_at": ts(end),
            "error_signature": safe_format(a["error_signature"]),
            "symptoms": [safe_format(s) for s in a["symptoms"]],
            "logs_snippet": safe_format(a["log_snippet"]),
            "deployment": {"version": deploy, "deployed_at": ts(start, -random.randint(5, 90))},
            "git_commit": commit,
            "root_cause": safe_format(a["root_cause"]),
            "investigation_steps": [safe_format(s) for s in a["investigation"]],
            "commands_used": [safe_format(c) for c in a["commands"]],
            "fix": safe_format(a["fix"]),
            "engineer": eng,
            "mttr_minutes": mttr,
            "outcome": "resolved",
        })
        inc_num += 1

    incidents.sort(key=lambda x: x["started_at"])
    # renumber chronologically
    for i, inc in enumerate(incidents, 1):
        inc["id"] = f"INC-{i:04d}"

    out = "/home/hatch/workspace/recall-sre/backend/data/incidents.json"
    with open(out, "w") as f:
        json.dump(incidents, f, indent=2)
    print(f"wrote {len(incidents)} incidents -> {out}")
    # quick sanity: archetype distribution via title keywords
    from collections import Counter
    print(Counter(i["title"].split()[0] + " " + i["title"].split()[1] for i in incidents))


if __name__ == "__main__":
    main()
