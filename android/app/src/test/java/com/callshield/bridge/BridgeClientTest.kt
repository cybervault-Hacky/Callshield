package com.callshield.bridge

import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test
import java.util.UUID

class BridgeClientTest {
    @Test
    fun daemonUnavailableFailsOpen() = runTest {
        val client = BridgeClient(
            socketPath = "/definitely/unavailable/callshield.sock",
            timeoutMs = 200
        )
        val result = client.screenNumber("+919876543210", UUID.randomUUID().toString())
        assertEquals("UNKNOWN", result.verdict)
        assertEquals("ALLOW", result.appliedAction)
        assertEquals("DRY_RUN", result.mode)
    }

    @Test
    fun invalidNumberFailsOpenWithoutTransport() = runTest {
        val client = BridgeClient(socketPath = "/unavailable.sock", timeoutMs = 200)
        val result = client.screenNumber("not-a-number", UUID.randomUUID().toString())
        assertEquals("UNKNOWN", result.verdict)
        assertEquals("ALLOW", result.appliedAction)
        assertEquals("INVALID_NUMBER", result.reason)
    }

    @Test
    fun invalidRequestIdFailsOpenWithoutTransport() = runTest {
        val client = BridgeClient(socketPath = "/unavailable.sock", timeoutMs = 200)
        val result = client.screenNumber("+919876543210", "invalid-id")
        assertEquals("UNKNOWN", result.verdict)
        assertEquals("ALLOW", result.appliedAction)
        assertEquals("INVALID_REQUEST_ID", result.reason)
    }
}
