package com.voiceagent.app

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.media.AudioManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.View
import android.view.WindowManager
import android.widget.EditText
import android.widget.ImageButton
import android.widget.Toast
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class MainActivity : Activity(), CallController.Listener {

    private enum class UiState { IDLE, CONNECTING, IN_CALL }

    private lateinit var wave: WaveView
    private lateinit var btnCall: ImageButton
    private lateinit var swAsr: ProviderSwitch
    private lateinit var swTts: ProviderSwitch

    private val handler = Handler(Looper.getMainLooper())
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)   // 首次切本地模型要加载数秒
        .writeTimeout(5, TimeUnit.SECONDS)
        .build()
    private val prefs by lazy { getSharedPreferences("voice_agent", Context.MODE_PRIVATE) }
    private val circleBg = GradientDrawable().apply { shape = GradientDrawable.OVAL }
    private var controller: CallController? = null
    private var uiState = UiState.IDLE
    private var pendingCall = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility =
            View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
            View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or
            View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
            View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
            View.SYSTEM_UI_FLAG_FULLSCREEN or
            View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY

        wave = findViewById(R.id.wave)
        btnCall = findViewById(R.id.btnCall)
        swAsr = findViewById(R.id.swAsr)
        swTts = findViewById(R.id.swTts)
        swAsr.setLabel("识别")
        swTts.setLabel("合成")
        swAsr.onToggle = { idx -> switchProvider("asr", swAsr, idx) }
        swTts.onToggle = { idx -> switchProvider("tts", swTts, idx) }
        btnCall.setOnClickListener { onCallButton() }
        findViewById<View>(R.id.btnSettings).setOnClickListener { showSettings() }
        setUiState(UiState.IDLE)

        if (host().isEmpty()) showSettings() else refreshProviders()
    }

    override fun onDestroy() {
        controller?.stop()
        super.onDestroy()
    }

    private fun host(): String = prefs.getString("host", "") ?: ""

    // ---------- 通话 ----------

    private fun onCallButton() {
        when (uiState) {
            UiState.IDLE -> {
                if (host().isEmpty()) { showSettings(); return }
                if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) !=
                    PackageManager.PERMISSION_GRANTED) {
                    pendingCall = true
                    requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1)
                    return
                }
                startCall()
            }
            else -> endCall()
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int, permissions: Array<out String>, grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (pendingCall &&
            grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
            startCall()
        } else if (pendingCall) {
            toast("需要麦克风权限才能通话")
        }
        pendingCall = false
    }

    private fun startCall() {
        setUiState(UiState.CONNECTING)
        val c = CallController(getSystemService(AUDIO_SERVICE) as AudioManager, this)
        controller = c
        c.start(host())
    }

    private fun endCall() {
        controller?.stop()
        controller = null
        setUiState(UiState.IDLE)
    }

    // ---- CallController.Listener（后台线程回调） ----

    override fun onOpen() {
        handler.post { setUiState(UiState.IN_CALL) }
    }

    override fun onClosed(reason: String?) {
        handler.post {
            controller = null
            if (uiState != UiState.IDLE) setUiState(UiState.IDLE)
            reason?.let { toast(it) }
        }
    }

    override fun onUserLevel(rms: Float) = wave.onUserRms(rms)

    override fun onAgentLevel(rms: Float) = wave.onAgentRms(rms)

    private fun setUiState(s: UiState) {
        uiState = s
        circleBg.setColor(when (s) {
            UiState.IDLE -> Color.rgb(0x1d, 0xb9, 0x54)
            UiState.CONNECTING -> Color.rgb(0xd9, 0xa5, 0x14)
            UiState.IN_CALL -> Color.rgb(0xe5, 0x48, 0x4d)
        })
        btnCall.background = circleBg
        btnCall.animate()
            .rotation(if (s == UiState.IN_CALL) 135f else 0f)
            .setDuration(200).start()
        wave.state = when (s) {
            UiState.IDLE -> WaveView.State.IDLE
            UiState.CONNECTING -> WaveView.State.CONNECTING
            UiState.IN_CALL -> WaveView.State.IN_CALL
        }
    }

    // ---------- provider 切换（与 web 版同一 API） ----------

    private fun refreshProviders() {
        val h = host()
        if (h.isEmpty()) return
        Thread {
            try {
                http.newCall(Request.Builder().url("http://$h/api/providers").build())
                    .execute().use { resp ->
                        if (!resp.isSuccessful) return@use
                        val body = resp.body?.string() ?: return@use
                        val obj = JSONObject(body)
                        val asr = obj.getJSONObject("asr").getString("active")
                        val tts = obj.getJSONObject("tts").getString("active")
                        handler.post {
                            swAsr.setSelected(if (asr == "sherpa") 0 else 1)
                            swTts.setSelected(if (tts == "sherpa") 0 else 1)
                        }
                    }
            } catch (e: Exception) { }
        }.start()
    }

    private fun switchProvider(slot: String, sw: ProviderSwitch, idx: Int) {
        val h = host()
        if (h.isEmpty()) {
            sw.setSelected(if (idx == 0) 1 else 0)
            showSettings()
            return
        }
        sw.loading = true
        Thread {
            val ok = try {
                val body = JSONObject()
                    .put(slot, if (idx == 0) "sherpa" else "volcengine")
                    .toString()
                    .toRequestBody("application/json".toMediaType())
                http.newCall(Request.Builder().url("http://$h/api/providers").post(body).build())
                    .execute().use { it.isSuccessful }
            } catch (e: Exception) { false }
            handler.post {
                sw.loading = false
                if (!ok) {
                    sw.setSelected(if (idx == 0) 1 else 0)
                    sw.shake()
                    toast("切换失败")
                }
            }
        }.start()
    }

    // ---------- 设置 ----------

    private fun showSettings() {
        val pad = (20 * resources.displayMetrics.density).toInt()
        val edit = EditText(this).apply {
            setText(host())
            hint = "电脑IP:端口，如 192.168.1.5:8080"
            inputType = InputType.TYPE_CLASS_TEXT
            setSingleLine()
            setPadding(pad, pad / 2, pad, pad / 2)
        }
        AlertDialog.Builder(this)
            .setTitle("服务器地址")
            .setView(edit)
            .setPositiveButton("保存") { _, _ ->
                val v = edit.text.toString().trim()
                prefs.edit().putString("host", v).apply()
                if (v.isNotEmpty()) refreshProviders()
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}
