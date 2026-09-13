//go:build windows

package main

import (
	"time"
)

// BackendHealthState separates process lifetime from application responsiveness.
type BackendHealthState string

const (
	BackendHealthy      BackendHealthState = "healthy"
	BackendDegraded     BackendHealthState = "degraded"
	BackendUnresponsive BackendHealthState = "unresponsive"
	BackendDead         BackendHealthState = "dead"
)

type backendProbeFns struct {
	processAlive func(int) bool
	status       func(int, time.Duration) ProbeResult
	auth         func(int, string, time.Duration) ProbeResult
	now          func() time.Time
	sleep        func(time.Duration)
}

func (bm *BackendManager) probes() backendProbeFns {
	p := bm.probeHooks
	if p.processAlive == nil {
		p.processAlive = processAlive
	}
	if p.status == nil {
		p.status = probeBackendStatus
	}
	if p.auth == nil {
		p.auth = probeBackendAuth
	}
	if p.now == nil {
		p.now = time.Now
	}
	if p.sleep == nil {
		p.sleep = time.Sleep
	}
	return p
}

func (bm *BackendManager) recordProbeOK(now time.Time, kind ProbeKind, latency time.Duration) {
	bm.healthMu.Lock()
	defer bm.healthMu.Unlock()
	bm.softFailures = 0
	bm.firstSoftFailureAt = time.Time{}
	bm.lastProbeOKAt = now
	bm.health = BackendHealthy
	bm.lastProbeKind = kind.String()
	bm.lastProbeLatency = latency
}

func (bm *BackendManager) recordSoftFailure(now time.Time, kind ProbeKind, latency time.Duration) BackendHealthState {
	bm.healthMu.Lock()
	defer bm.healthMu.Unlock()
	bm.softFailures++
	if bm.firstSoftFailureAt.IsZero() {
		bm.firstSoftFailureAt = now
	}
	bm.lastProbeKind = kind.String()
	bm.lastProbeLatency = latency
	threshold := bm.cfg.softFailThreshold()
	grace := bm.cfg.unresponsiveGrace()
	if bm.softFailures >= threshold && now.Sub(bm.firstSoftFailureAt) >= grace {
		bm.health = BackendUnresponsive
	} else {
		bm.health = BackendDegraded
	}
	return bm.health
}

func (bm *BackendManager) recordDead(kind string) {
	bm.healthMu.Lock()
	defer bm.healthMu.Unlock()
	bm.health = BackendDead
	bm.lastProbeKind = kind
}

func (bm *BackendManager) HealthSnapshot() (BackendHealthState, int, time.Time, time.Time, string, time.Duration) {
	bm.healthMu.Lock()
	defer bm.healthMu.Unlock()
	return bm.health, bm.softFailures, bm.firstSoftFailureAt, bm.lastProbeOKAt, bm.lastProbeKind, bm.lastProbeLatency
}

// shouldReplaceOwnedBackend returns policy only — it must not kill processes.
func (bm *BackendManager) shouldReplaceOwnedBackend(state BackendHealthState, now time.Time) bool {
	switch state {
	case BackendDead:
		return true
	case BackendUnresponsive:
		bm.healthMu.Lock()
		fails := bm.softFailures
		first := bm.firstSoftFailureAt
		bm.healthMu.Unlock()
		if fails < bm.cfg.softFailThreshold() {
			return false
		}
		if first.IsZero() {
			return false
		}
		return now.Sub(first) >= bm.cfg.unresponsiveGrace()
	default:
		return false
	}
}

func (bm *BackendManager) graceRemaining(now time.Time) time.Duration {
	bm.healthMu.Lock()
	defer bm.healthMu.Unlock()
	if bm.firstSoftFailureAt.IsZero() {
		return bm.cfg.unresponsiveGrace()
	}
	elapsed := now.Sub(bm.firstSoftFailureAt)
	rem := bm.cfg.unresponsiveGrace() - elapsed
	if rem < 0 {
		return 0
	}
	return rem
}

func (bm *BackendManager) stopInvoked() bool {
	bm.healthMu.Lock()
	defer bm.healthMu.Unlock()
	return bm.stopCount > 0
}

func (bm *BackendManager) resetStopCount() {
	bm.healthMu.Lock()
	bm.stopCount = 0
	bm.healthMu.Unlock()
}
