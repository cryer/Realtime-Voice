package com.voiceagent.app

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/**
 * 一通电话的完整生命周期：WS 连接 + 麦克风上行 + TTS 下行播放 + barge-in flush。
 * 协议与 web 版一致（voice/transport/web_ws.py）：
 * 上行二进制 = 16kHz PCM16 mono 1024B(32ms) 帧；下行二进制 = TTS 音频；
 * 下行 JSON = {"type":"flush"|"eos"}；挂断发 {"type":"hangup"}。
 */
class CallController(
    private val audioManager: AudioManager,
    private val listener: Listener,
) {
    interface Listener {
        fun onOpen()
        fun onClosed(reason: String?)
        fun onUserLevel(rms: Float)
        fun onAgentLevel(rms: Float)
    }

    @Volatile private var running = false
    @Volatile private var audioActive = false
    @Volatile private var flushEpoch = 0
    private var client: OkHttpClient? = null
    private var ws: WebSocket? = null
    private var recorder: AudioRecord? = null
    private var track: AudioTrack? = null
    private var captureThread: Thread? = null
    private var playbackThread: Thread? = null
    private val playQueue = LinkedBlockingQueue<ByteArray>()
    private var savedMode = AudioManager.MODE_NORMAL
    private var savedSpeaker = false

    fun start(host: String) {
        running = true
        val c = OkHttpClient.Builder()
            .pingInterval(20, TimeUnit.SECONDS)
            .build()
        client = c
        c.newWebSocket(Request.Builder().url("ws://$host/ws").build(), socketListener)
    }

    /** 用户挂断。 */
    fun stop() {
        running = false
        try { ws?.send("{\"type\":\"hangup\"}") } catch (e: Exception) { }
        ws?.close(1000, null)
        stopAudio()
        client?.dispatcher?.executorService?.shutdown()
        client = null
        ws = null
    }

    private val socketListener = object : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            ws = webSocket
            startAudio()
            listener.onOpen()
        }

        override fun onMessage(webSocket: WebSocket, bytes: okio.ByteString) {
            val data = bytes.toByteArray()
            val n = data.size / 2
            if (n > 0) {
                var sum = 0.0
                for (i in 0 until n) {
                    val v = (data[i * 2].toInt() and 0xff) or (data[i * 2 + 1].toInt() shl 8)
                    val s = v.toShort().toInt()
                    sum += (s * s).toDouble()
                }
                listener.onAgentLevel((sqrt(sum / n) / 32768.0).toFloat())
            }
            if (running) playQueue.offer(data)
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            val type = try { JSONObject(text).optString("type") } catch (e: Exception) { "" }
            if (type == "flush") flushPlayback()   // barge-in：立即清缓冲静音
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(1000, null)
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            stopAudio()
            listener.onClosed(null)
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            stopAudio()
            listener.onClosed(t.message ?: "连接失败")
        }
    }

    @Synchronized
    private fun startAudio() {
        if (audioActive) return
        audioActive = true
        // VOICE_COMMUNICATION + 扬声器：走设备硬件 AEC（对应 web 版 echoCancellation）
        savedMode = audioManager.mode
        savedSpeaker = audioManager.isSpeakerphoneOn
        audioManager.mode = AudioManager.MODE_IN_COMMUNICATION
        audioManager.isSpeakerphoneOn = true

        val minPlay = AudioTrack.getMinBufferSize(
            SAMPLE_RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
        track = AudioTrack.Builder()
            .setAudioAttributes(AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                .build())
            .setAudioFormat(AudioFormat.Builder()
                .setSampleRate(SAMPLE_RATE)
                .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                .build())
            .setBufferSizeInBytes(max(minPlay, 8192))
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()
        track?.play()
        playbackThread = Thread(::playbackLoop, "tts-playback").apply { start() }

        recorder = createRecorder()
        if (recorder == null) {
            listener.onClosed("麦克风初始化失败")
            return
        }
        recorder?.startRecording()
        captureThread = Thread(::captureLoop, "mic-capture").apply { start() }
    }

    private fun createRecorder(): AudioRecord? {
        val minRec = AudioRecord.getMinBufferSize(
            SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        for (source in intArrayOf(
            MediaRecorder.AudioSource.VOICE_COMMUNICATION,
            MediaRecorder.AudioSource.MIC)) {
            try {
                val r = AudioRecord(source, SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT, max(minRec, 4096))
                if (r.state == AudioRecord.STATE_INITIALIZED) return r
                r.release()
            } catch (e: Exception) { }
        }
        return null
    }

    private fun captureLoop() {
        val rec = recorder ?: return
        val frame = ShortArray(FRAME_SAMPLES)
        var carry = ByteArray(0)
        while (running) {
            val n = rec.read(frame, 0, frame.size)
            if (n <= 0) continue
            var sum = 0.0
            val bb = ByteBuffer.allocate(n * 2).order(ByteOrder.LITTLE_ENDIAN)
            for (i in 0 until n) {
                sum += (frame[i].toInt() * frame[i].toInt()).toDouble()
                bb.putShort(frame[i])
            }
            listener.onUserLevel((sqrt(sum / n) / 32768.0).toFloat())
            carry += bb.array()
            while (carry.size >= FRAME_BYTES && running) {
                ws?.send(carry.copyOfRange(0, FRAME_BYTES).toByteString())
                carry = carry.copyOfRange(FRAME_BYTES, carry.size)
            }
        }
    }

    private fun playbackLoop() {
        val tr = track ?: return
        while (running) {
            val chunk = playQueue.poll(100, TimeUnit.MILLISECONDS) ?: continue
            val epoch = flushEpoch
            var off = 0
            // 切 ≤20ms 小写，保证 flush 后静音延迟低
            while (off < chunk.size && running && epoch == flushEpoch) {
                val len = min(FLUSH_SLICE_BYTES, chunk.size - off)
                val w = tr.write(chunk, off, len)
                if (w > 0) off += w
            }
        }
    }

    private fun flushPlayback() {
        flushEpoch++
        playQueue.clear()
        track?.let {
            if (it.playState == AudioTrack.PLAYSTATE_PLAYING) it.pause()
            it.flush()
            it.play()
        }
    }

    @Synchronized
    private fun stopAudio() {
        if (!audioActive) return
        audioActive = false
        running = false
        captureThread?.join(500)
        playbackThread?.join(500)
        captureThread = null
        playbackThread = null
        try { recorder?.stop() } catch (e: Exception) { }
        recorder?.release()
        recorder = null
        try { track?.stop() } catch (e: Exception) { }
        track?.release()
        track = null
        playQueue.clear()
        audioManager.mode = savedMode
        audioManager.isSpeakerphoneOn = savedSpeaker
    }

    private companion object {
        const val SAMPLE_RATE = 16000
        const val FRAME_SAMPLES = 512       // 32ms
        const val FRAME_BYTES = 1024
        const val FLUSH_SLICE_BYTES = 640   // 20ms
    }
}
