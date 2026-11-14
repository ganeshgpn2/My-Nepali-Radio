# -*- coding: utf-8 -*-
"""Adds the native player, widget and Android bridge to the Capacitor Android project.
Run from the repository root AFTER `npx cap add android`."""
import os, re

FILES = {
'android/app/src/main/java/com/nepaliradio/app/MainActivity.java': r'''package com.nepaliradio.app;

import android.media.AudioManager;
import android.os.Bundle;
import android.webkit.ValueCallback;
import android.webkit.WebView;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setVolumeControlStream(AudioManager.STREAM_MUSIC);
        WebView w = getBridge().getWebView();
        w.addJavascriptInterface(new NativeBridge(this, w), "Android");
        final WebView fw = w;
        // Safety net: if the page loaded before the bridge existed, reload it once.
        fw.postDelayed(new Runnable() {
            @Override
            public void run() {
                fw.evaluateJavascript("typeof window.Android", new ValueCallback<String>() {
                    @Override
                    public void onReceiveValue(String v) {
                        if (v != null && v.contains("undefined")) fw.reload();
                    }
                });
            }
        }, 2500);
    }

    @Override
    public void onResume() {
        super.onResume();
        NativeBridge b = NativeBridge.current;
        if (b != null) b.emitState();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        NativeBridge b = NativeBridge.current;
        if (b != null) b.emit("{\"t\":\"res\"}");
    }

    @Override
    public void onDestroy() {
        NativeBridge.current = null;
        super.onDestroy();
    }
}
''',
'android/app/src/main/java/com/nepaliradio/app/NativeBridge.java': r'''package com.nepaliradio.app;

import android.Manifest;
import android.app.Activity;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.os.PowerManager;
import android.provider.MediaStore;
import android.provider.Settings;
import android.util.Base64;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;

/** The "Android" object that the HTML app talks to. */
public class NativeBridge {
    static volatile NativeBridge current;

    private final Activity activity;
    private final WebView web;
    private final SharedPreferences sp;

    NativeBridge(Activity a, WebView w) {
        activity = a;
        web = w;
        sp = a.getSharedPreferences("nr", Context.MODE_PRIVATE);
        current = this;
    }

    /* ---------- native -> JS ---------- */

    void emit(final String json) {
        web.post(new Runnable() {
            @Override
            public void run() {
                web.evaluateJavascript("window.__nat&&window.__nat(" + json + ")", null);
            }
        });
    }

    void emitPl(String state, String key, boolean sleepDone) {
        try {
            JSONObject o = new JSONObject();
            o.put("t", "pl");
            o.put("s", state);
            if (key != null && key.length() > 0) o.put("k", key);
            if (sleepDone) o.put("sleepDone", true);
            emit(o.toString());
        } catch (Exception e) {
        }
    }

    void emitState() {
        try {
            emit(getPlayerState());
        } catch (Exception e) {
        }
    }

    /* ---------- player ---------- */

    @JavascriptInterface
    public boolean isNative() {
        return true;
    }

    @JavascriptInterface
    public void playQueue(String json, int index, double vol) {
        try {
            JSONArray in = new JSONArray(json);
            JSONArray out = new JSONArray();
            File dir = new File(activity.getFilesDir(), "logos");
            if (!dir.exists()) dir.mkdirs();
            for (int i = 0; i < in.length(); i++) {
                JSONObject o = in.getJSONObject(i);
                String l = o.optString("l", "");
                if (l.startsWith("data:") && l.indexOf(',') > 0) {
                    saveLogo(dir, o.optString("k"), l);
                }
                o.remove("l");
                out.put(o);
            }
            sp.edit().putString("queue", out.toString()).putInt("idx", index).putFloat("vol", (float) vol).apply();
            askNotifPermissionOnce();
            PlayerService.send(activity, PlayerService.A_PLAY);
        } catch (Exception e) {
        }
    }

    private void saveLogo(File dir, String key, String dataUrl) {
        try {
            byte[] b = Base64.decode(dataUrl.substring(dataUrl.indexOf(',') + 1), Base64.DEFAULT);
            Bitmap bm = BitmapFactory.decodeByteArray(b, 0, b.length);
            if (bm == null) return;
            int s = 160;
            Bitmap sm = Bitmap.createScaledBitmap(bm, s, s, true);
            FileOutputStream fo = new FileOutputStream(new File(dir, PlayerService.safe(key) + ".png"));
            sm.compress(Bitmap.CompressFormat.PNG, 90, fo);
            fo.close();
        } catch (Throwable t) {
        }
    }

    private void askNotifPermissionOnce() {
        if (Build.VERSION.SDK_INT < 33) return;
        if (sp.getBoolean("askedNotif", false)) return;
        if (activity.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) return;
        sp.edit().putBoolean("askedNotif", true).apply();
        activity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                activity.requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 77);
            }
        });
    }

    @JavascriptInterface
    public void pause() {
        PlayerService.send(activity, PlayerService.A_PAUSE);
    }

    @JavascriptInterface
    public void stop() {
        PlayerService.send(activity, PlayerService.A_STOP);
    }

    @JavascriptInterface
    public void setVolume(double v) {
        sp.edit().putFloat("vol", (float) v).apply();
        PlayerService.send(activity, PlayerService.A_VOL);
    }

    @JavascriptInterface
    public void setSleep(int minutes) {
        sp.edit().putInt("sleep", minutes).apply();
        PlayerService.send(activity, PlayerService.A_SLEEP);
    }

    @JavascriptInterface
    public String getPlayerState() {
        try {
            String st = sp.getString("state", "idle");
            JSONObject o = new JSONObject();
            o.put("t", "pl");
            o.put("s", st);
            JSONArray q = new JSONArray(sp.getString("queue", "[]"));
            int i = sp.getInt("idx", 0);
            if (i >= 0 && i < q.length()) o.put("k", q.getJSONObject(i).optString("k"));
            return o.toString();
        } catch (Exception e) {
            return "{\"t\":\"pl\",\"s\":\"idle\"}";
        }
    }

    @JavascriptInterface
    public void setWidgetTheme(String json) {
        sp.edit().putString("wtheme", json == null ? "{}" : json).apply();
        RadioWidgetProvider.refresh(activity);
    }

    /* ---------- recording (not in this build) ---------- */

    @JavascriptInterface
    public String getRecState() {
        return "{\"on\":false}";
    }

    @JavascriptInterface
    public void startRec(String name, String url, int dur) {
        emit("{\"t\":\"rec\",\"on\":false,\"msg\":\"रेकर्डिङ यो एपमा अहिले उपलब्ध छैन।\"}");
    }

    @JavascriptInterface
    public void stopRec() {
    }

    @JavascriptInterface
    public String listRecs() {
        return "[]";
    }

    @JavascriptInterface
    public String recAction(String id, String action, String arg) {
        return "ok";
    }

    /* ---------- alarms (stored only, not fired in this build) ---------- */

    @JavascriptInterface
    public void setAlarms(String json) {
        sp.edit().putString("alarms", json).apply();
    }

    @JavascriptInterface
    public String getAlarms() {
        return sp.getString("alarms", "[]");
    }

    @JavascriptInterface
    public void setRecSchedules(String json) {
        sp.edit().putString("recsched", json).apply();
    }

    /* ---------- offline fallback (not in this build) ---------- */

    @JavascriptInterface
    public String getOffline() {
        return "[]";
    }

    @JavascriptInterface
    public boolean getOfflineAny() {
        return false;
    }

    @JavascriptInterface
    public void setOfflineAny(boolean on) {
    }

    @JavascriptInterface
    public void pickOffline() {
    }

    @JavascriptInterface
    public void clearOffline() {
    }

    /* ---------- TV helpers (not in this build) ---------- */

    @JavascriptInterface
    public void setTvPlaying(boolean on) {
    }

    @JavascriptInterface
    public void setTvPaused(boolean on) {
    }

    @JavascriptInterface
    public boolean tvRecOpen(String fname, String name) {
        return false;
    }

    @JavascriptInterface
    public void tvRecWrite(String b64) {
    }

    @JavascriptInterface
    public void tvRecClose(double ms) {
    }

    /* ---------- permissions ---------- */

    @JavascriptInterface
    public String permStatus() {
        try {
            JSONObject o = new JSONObject();
            boolean notif = Build.VERSION.SDK_INT < 33
                    || activity.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
            boolean bat = true;
            if (Build.VERSION.SDK_INT >= 23) {
                PowerManager pm = (PowerManager) activity.getSystemService(Context.POWER_SERVICE);
                bat = pm.isIgnoringBatteryOptimizations(activity.getPackageName());
            }
            o.put("notif", notif);
            o.put("exact", true);
            o.put("battery", bat);
            o.put("fsi", true);
            o.put("dnd", true);
            return o.toString();
        } catch (Exception e) {
            return "{}";
        }
    }

    @JavascriptInterface
    public void openPerm(final String what) {
        activity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                try {
                    if ("notif".equals(what) && Build.VERSION.SDK_INT >= 33) {
                        activity.requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 77);
                    } else if ("battery".equals(what) && Build.VERSION.SDK_INT >= 23) {
                        activity.startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));
                    } else {
                        Intent i = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
                        i.setData(Uri.parse("package:" + activity.getPackageName()));
                        activity.startActivity(i);
                    }
                } catch (Exception e) {
                }
            }
        });
    }

    /* ---------- backup files ---------- */

    @JavascriptInterface
    public String saveBackup(String name, String text) {
        try {
            return write(name, text.getBytes("UTF-8"));
        } catch (Exception e) {
            return "सेभ गर्न सकिएन।";
        }
    }

    @JavascriptInterface
    public String saveBackupBase64(String name, String b64) {
        try {
            return write(name, Base64.decode(b64, Base64.DEFAULT));
        } catch (Exception e) {
            return "सेभ गर्न सकिएन।";
        }
    }

    private String write(String name, byte[] data) throws Exception {
        String safeName = name.replaceAll("[\\\\/:*?\"<>|]+", "-");
        String low = safeName.toLowerCase();
        String mime = low.endsWith(".json") ? "application/json"
                : low.endsWith(".xlsx") ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                : low.endsWith(".xls") ? "application/vnd.ms-excel" : "text/plain";
        if (Build.VERSION.SDK_INT >= 29) {
            ContentValues v = new ContentValues();
            v.put(MediaStore.MediaColumns.DISPLAY_NAME, safeName);
            v.put(MediaStore.MediaColumns.MIME_TYPE, mime);
            v.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS);
            Uri u = activity.getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
            if (u == null) throw new Exception("no uri");
            OutputStream os = activity.getContentResolver().openOutputStream(u);
            os.write(data);
            os.close();
            return "फाइल Download फोल्डरमा सेभ भयो: " + safeName;
        }
        File dir = activity.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
        if (dir == null) dir = activity.getFilesDir();
        dir.mkdirs();
        File f = new File(dir, safeName);
        FileOutputStream fo = new FileOutputStream(f);
        fo.write(data);
        fo.close();
        return "फाइल सेभ भयो: " + f.getAbsolutePath();
    }
}
''',
'android/app/src/main/java/com/nepaliradio/app/PlayerService.java': r'''package com.nepaliradio.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

import androidx.media3.common.AudioAttributes;
import androidx.media3.common.C;
import androidx.media3.common.MediaItem;
import androidx.media3.common.PlaybackException;
import androidx.media3.common.Player;
import androidx.media3.datasource.DefaultHttpDataSource;
import androidx.media3.exoplayer.ExoPlayer;
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;

/** Plays the radio in the background; also drives the notification and the home-screen widget. */
public class PlayerService extends Service {
    static final String A_PLAY = "com.nepaliradio.app.PLAY";
    static final String A_TOGGLE = "com.nepaliradio.app.TOGGLE";
    static final String A_PAUSE = "com.nepaliradio.app.PAUSE";
    static final String A_PREV = "com.nepaliradio.app.PREV";
    static final String A_NEXT = "com.nepaliradio.app.NEXT";
    static final String A_STOP = "com.nepaliradio.app.STOP";
    static final String A_VOL = "com.nepaliradio.app.VOL";
    static final String A_SLEEP = "com.nepaliradio.app.SLEEP";

    private static final String CHANNEL = "radio_play";
    private static final int NID = 7;

    private ExoPlayer player;
    private SharedPreferences sp;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private Runnable sleepRun;
    private String state = "idle";

    static void send(Context c, String action) {
        Intent i = new Intent(c, PlayerService.class);
        i.setAction(action);
        if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(i);
        else c.startService(i);
    }

    static String safe(String k) {
        return k == null ? "x" : k.replaceAll("[^A-Za-z0-9_-]", "_");
    }

    @Override
    public void onCreate() {
        super.onCreate();
        sp = getSharedPreferences("nr", Context.MODE_PRIVATE);
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "रेडियो", NotificationManager.IMPORTANCE_LOW);
            ch.setShowBadge(false);
            ((NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE)).createNotificationChannel(ch);
        }
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        goForeground();
        String a = intent == null ? null : intent.getAction();
        if (a == null) return START_NOT_STICKY;
        try {
            if (A_PLAY.equals(a)) {
                playIndex(sp.getInt("idx", 0));
            } else if (A_TOGGLE.equals(a)) {
                if (state.equals("playing") || state.equals("loading")) pausePlayback();
                else playIndex(sp.getInt("idx", 0));
            } else if (A_PAUSE.equals(a)) {
                pausePlayback();
            } else if (A_PREV.equals(a)) {
                playIndex(sp.getInt("idx", 0) - 1);
            } else if (A_NEXT.equals(a)) {
                playIndex(sp.getInt("idx", 0) + 1);
            } else if (A_STOP.equals(a)) {
                stopPlayback(false);
            } else if (A_VOL.equals(a)) {
                if (player != null) player.setVolume(sp.getFloat("vol", 0.9f));
            } else if (A_SLEEP.equals(a)) {
                setSleep(sp.getInt("sleep", 0));
            }
        } catch (Throwable t) {
            setState("error");
        }
        return START_NOT_STICKY;
    }

    /* ---------- queue ---------- */

    private JSONArray queue() {
        try {
            return new JSONArray(sp.getString("queue", "[]"));
        } catch (Exception e) {
            return new JSONArray();
        }
    }

    private String currentKey() {
        try {
            JSONObject o = queue().optJSONObject(sp.getInt("idx", 0));
            return o == null ? "" : o.optString("k");
        } catch (Exception e) {
            return "";
        }
    }

    /* ---------- playback ---------- */

    private void ensurePlayer() {
        if (player != null) return;
        DefaultHttpDataSource.Factory http = new DefaultHttpDataSource.Factory()
                .setUserAgent("Mozilla/5.0 (Linux; Android) NepaliRadio/1.0")
                .setAllowCrossProtocolRedirects(true)
                .setConnectTimeoutMs(15000)
                .setReadTimeoutMs(15000);
        player = new ExoPlayer.Builder(this)
                .setMediaSourceFactory(new DefaultMediaSourceFactory(http))
                .setAudioAttributes(new AudioAttributes.Builder()
                        .setUsage(C.USAGE_MEDIA)
                        .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
                        .build(), true)
                .setHandleAudioBecomingNoisy(true)
                .setWakeMode(C.WAKE_MODE_NETWORK)
                .build();
        player.addListener(new Player.Listener() {
            @Override
            public void onPlaybackStateChanged(int s) {
                if (player == null) return;
                if (s == Player.STATE_READY && player.getPlayWhenReady()) setState("playing");
                else if (s == Player.STATE_BUFFERING && player.getPlayWhenReady()) setState("loading");
                else if (s == Player.STATE_ENDED) setState("error");
            }

            @Override
            public void onIsPlayingChanged(boolean p) {
                if (p) setState("playing");
            }

            @Override
            public void onPlayWhenReadyChanged(boolean pwr, int reason) {
                if (!pwr && (state.equals("playing") || state.equals("loading"))) setState("paused");
            }

            @Override
            public void onPlayerError(PlaybackException e) {
                setState("error");
            }
        });
    }

    private void playIndex(int i) {
        JSONArray q = queue();
        int n = q.length();
        if (n == 0) {
            stopPlayback(false);
            return;
        }
        i = ((i % n) + n) % n;
        sp.edit().putInt("idx", i).apply();
        JSONObject o = q.optJSONObject(i);
        String u = o == null ? "" : o.optString("u");
        if (u.length() == 0) {
            setState("error");
            return;
        }
        ensurePlayer();
        player.setVolume(sp.getFloat("vol", 0.9f));
        setState("loading");
        player.setMediaItem(MediaItem.fromUri(Uri.parse(u)));
        player.prepare();
        player.setPlayWhenReady(true);
    }

    private void pausePlayback() {
        if (player != null) player.setPlayWhenReady(false);
        setState("paused");
    }

    private void stopPlayback(boolean sleepDone) {
        cancelSleep();
        if (player != null) {
            player.stop();
            player.release();
            player = null;
        }
        state = "idle";
        sp.edit().putString("state", "idle").apply();
        NativeBridge b = NativeBridge.current;
        if (b != null) b.emitPl("idle", currentKey(), sleepDone);
        RadioWidgetProvider.refresh(this);
        if (Build.VERSION.SDK_INT >= 24) stopForeground(Service.STOP_FOREGROUND_REMOVE);
        else stopForeground(true);
        stopSelf();
    }

    private void cancelSleep() {
        if (sleepRun != null) handler.removeCallbacks(sleepRun);
        sleepRun = null;
    }

    private void setSleep(int minutes) {
        cancelSleep();
        if (minutes <= 0) return;
        sleepRun = new Runnable() {
            @Override
            public void run() {
                sleepRun = null;
                stopPlayback(true);
            }
        };
        handler.postDelayed(sleepRun, minutes * 60000L);
    }

    private void setState(String s) {
        if (s.equals(state)) return;
        state = s;
        sp.edit().putString("state", s).apply();
        goForeground();
        RadioWidgetProvider.refresh(this);
        NativeBridge b = NativeBridge.current;
        if (b != null) b.emitPl(s, currentKey(), false);
    }

    /* ---------- notification ---------- */

    private PendingIntent act(String action, int code) {
        Intent i = new Intent(this, PlayerService.class);
        i.setAction(action);
        int fl = PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0);
        if (Build.VERSION.SDK_INT >= 26) return PendingIntent.getForegroundService(this, code, i, fl);
        return PendingIntent.getService(this, code, i, fl);
    }

    private void goForeground() {
        Notification n = buildNotification();
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);
        } else {
            startForeground(NID, n);
        }
    }

    private Notification buildNotification() {
        String name = "नेपाली रेडियो";
        String key = "";
        try {
            JSONObject o = queue().optJSONObject(sp.getInt("idx", 0));
            if (o != null) {
                name = o.optString("n", name);
                key = o.optString("k");
                double f = o.optDouble("f", 0);
                if (f > 0) name = name + " · " + String.format(java.util.Locale.US, "%.1f", f);
            }
        } catch (Exception e) {
        }
        boolean on = state.equals("playing") || state.equals("loading");
        String sub = state.equals("playing") ? "● LIVE" : state.equals("loading") ? "लोड हुँदै…"
                : state.equals("paused") ? "रोकिएको" : state.equals("error") ? "बज्न सकेन" : "नेपाली रेडियो";

        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= 26) b = new Notification.Builder(this, CHANNEL);
        else b = new Notification.Builder(this);

        Intent open = new Intent(this, MainActivity.class);
        open.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_NEW_TASK);
        int fl = PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0);

        b.setSmallIcon(R.drawable.ic_stat_radio)
                .setContentTitle(name)
                .setContentText(sub)
                .setContentIntent(PendingIntent.getActivity(this, 0, open, fl))
                .setOngoing(on)
                .setShowWhen(false)
                .setVisibility(Notification.VISIBILITY_PUBLIC)
                .addAction(android.R.drawable.ic_media_previous, "अघिल्लो", act(A_PREV, 1))
                .addAction(on ? android.R.drawable.ic_media_pause : android.R.drawable.ic_media_play,
                        on ? "रोक्नुहोस्" : "बजाउनुहोस्", act(A_TOGGLE, 2))
                .addAction(android.R.drawable.ic_media_next, "अर्को", act(A_NEXT, 3))
                .addAction(android.R.drawable.ic_menu_close_clear_cancel, "बन्द", act(A_STOP, 4))
                .setStyle(new Notification.MediaStyle().setShowActionsInCompactView(0, 1, 2));
        try {
            File lf = new File(new File(getFilesDir(), "logos"), safe(key) + ".png");
            if (lf.exists()) {
                Bitmap bm = BitmapFactory.decodeFile(lf.getAbsolutePath());
                if (bm != null) b.setLargeIcon(bm);
            }
        } catch (Throwable t) {
        }
        return b.build();
    }

    @Override
    public void onDestroy() {
        cancelSleep();
        if (player != null) {
            player.release();
            player = null;
        }
        super.onDestroy();
    }
}
''',
'android/app/src/main/java/com/nepaliradio/app/RadioWidgetProvider.java': r'''package com.nepaliradio.app;

import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.widget.RemoteViews;

public class RadioWidgetProvider extends AppWidgetProvider {
    @Override
    public void onUpdate(Context context, AppWidgetManager mgr, int[] ids) {
        for (int id : ids) {
            try {
                mgr.updateAppWidget(id, WidgetRenderer.build(context));
            } catch (Throwable t) {
            }
        }
    }

    static void refresh(Context c) {
        try {
            AppWidgetManager mgr = AppWidgetManager.getInstance(c);
            int[] ids = mgr.getAppWidgetIds(new ComponentName(c, RadioWidgetProvider.class));
            if (ids == null || ids.length == 0) return;
            RemoteViews rv = WidgetRenderer.build(c);
            for (int id : ids) mgr.updateAppWidget(id, rv);
        } catch (Throwable t) {
        }
    }
}
''',
'android/app/src/main/java/com/nepaliradio/app/WidgetRenderer.java': r'''package com.nepaliradio.app;

import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.Configuration;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.BitmapShader;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RadialGradient;
import android.graphics.RectF;
import android.graphics.Shader;
import android.graphics.SweepGradient;
import android.graphics.Typeface;
import android.os.Build;
import android.widget.RemoteViews;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Draws the home-screen widget so that it looks like the mini player inside the app. */
final class WidgetRenderer {
    private WidgetRenderer() {
    }

    private static final class Theme {
        int bg1, bg2, ink, mut, line, chip, acc, d1, d2, dt, hub, hubi;
    }

    static RemoteViews build(Context c) {
        SharedPreferences sp = c.getSharedPreferences("nr", Context.MODE_PRIVATE);
        Theme t = theme(c, sp.getString("wtheme", "{}"));
        String state = sp.getString("state", "idle");
        String name = "नेपाली रेडियो";
        String key = "";
        double f = 0;
        try {
            JSONArray q = new JSONArray(sp.getString("queue", "[]"));
            JSONObject o = q.optJSONObject(sp.getInt("idx", 0));
            if (o != null) {
                name = o.optString("n", name);
                key = o.optString("k");
                f = o.optDouble("f", 0);
            }
        } catch (Exception e) {
        }
        boolean on = state.equals("playing") || state.equals("loading");
        String title = f > 0 ? name + " · " + String.format(java.util.Locale.US, "%.1f", f) : name;
        String sub = state.equals("playing") ? "● LIVE" : state.equals("loading") ? "लोड हुँदै…"
                : state.equals("paused") ? "रोकिएको" : state.equals("error") ? "बज्न सकेन"
                : "रेडियो सुन्न प्ले थिच्नुहोस्";

        RemoteViews rv = new RemoteViews(c.getPackageName(), R.layout.widget_player);
        rv.setImageViewBitmap(R.id.w_bg, bg(t));
        rv.setImageViewBitmap(R.id.w_logo, logo(c, t, key, name));
        rv.setImageViewBitmap(R.id.w_disc, disc(t, on));
        rv.setImageViewBitmap(R.id.w_prev, chip(t, 0));
        rv.setImageViewBitmap(R.id.w_next, chip(t, 1));
        rv.setImageViewBitmap(R.id.w_stop, chip(t, 2));
        rv.setTextViewText(R.id.w_title, title);
        rv.setTextViewText(R.id.w_sub, sub);
        rv.setTextColor(R.id.w_title, t.ink);
        rv.setTextColor(R.id.w_sub, state.equals("playing") ? t.acc : t.mut);

        rv.setOnClickPendingIntent(R.id.w_disc, svc(c, PlayerService.A_TOGGLE, 11));
        rv.setOnClickPendingIntent(R.id.w_prev, svc(c, PlayerService.A_PREV, 12));
        rv.setOnClickPendingIntent(R.id.w_next, svc(c, PlayerService.A_NEXT, 13));
        rv.setOnClickPendingIntent(R.id.w_stop, svc(c, PlayerService.A_STOP, 14));

        Intent open = new Intent(c, MainActivity.class);
        open.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        int fl = PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0);
        PendingIntent pi = PendingIntent.getActivity(c, 10, open, fl);
        rv.setOnClickPendingIntent(R.id.w_logo, pi);
        rv.setOnClickPendingIntent(R.id.w_text, pi);
        return rv;
    }

    private static PendingIntent svc(Context c, String action, int code) {
        Intent i = new Intent(c, PlayerService.class);
        i.setAction(action);
        int fl = PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0);
        if (Build.VERSION.SDK_INT >= 26) return PendingIntent.getForegroundService(c, code, i, fl);
        return PendingIntent.getService(c, code, i, fl);
    }

    /* ---------- theme ---------- */

    private static Theme theme(Context c, String json) {
        Theme t = new Theme();
        boolean dark = (c.getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK)
                == Configuration.UI_MODE_NIGHT_YES;
        JSONObject o = null;
        try {
            o = new JSONObject(json);
        } catch (Exception e) {
        }
        if (o == null || !o.has("bg")) {
            t.bg1 = t.bg2 = dark ? Color.parseColor("#1E1E22") : Color.WHITE;
            t.ink = dark ? Color.parseColor("#F2F2F2") : Color.parseColor("#1A1A1A");
            t.mut = dark ? Color.parseColor("#A9A9B2") : Color.parseColor("#666666");
            t.line = dark ? 0x33FFFFFF : 0x26000000;
            t.chip = dark ? 0x1FFFFFFF : 0x0F000000;
            t.acc = dark ? Color.parseColor("#FF6B81") : Color.parseColor("#C8102E");
            t.d1 = Color.parseColor("#C8102E");
            t.d2 = Color.parseColor("#5B0714");
            t.dt = Color.WHITE;
            t.hub = dark ? Color.parseColor("#1E1E22") : Color.WHITE;
            t.hubi = Color.parseColor("#C8102E");
            return t;
        }
        Matcher m = Pattern.compile("#[0-9A-Fa-f]{6}").matcher(o.optString("bg"));
        int[] g = new int[2];
        int n = 0;
        while (m.find() && n < 2) g[n++] = Color.parseColor(m.group());
        t.bg1 = n > 0 ? g[0] : Color.WHITE;
        t.bg2 = n > 1 ? g[1] : t.bg1;
        t.ink = col(o.optString("ink"), Color.WHITE);
        t.mut = col(o.optString("mut"), 0xCCFFFFFF);
        t.line = col(o.optString("line"), 0x47FFFFFF);
        t.chip = col(o.optString("chip"), 0x29FFFFFF);
        t.acc = col(o.optString("acc"), Color.WHITE);
        t.d1 = col(o.optString("d1"), Color.parseColor("#C8102E"));
        t.d2 = col(o.optString("d2"), Color.parseColor("#5B0714"));
        t.dt = col(o.optString("dt"), Color.WHITE);
        t.hub = col(o.optString("hub"), Color.WHITE);
        t.hubi = col(o.optString("hubi"), Color.parseColor("#C8102E"));
        return t;
    }

    private static int col(String s, int def) {
        try {
            s = s.trim();
            if (s.startsWith("#")) return Color.parseColor(s);
            if (s.startsWith("rgb")) {
                String in = s.substring(s.indexOf('(') + 1, s.lastIndexOf(')'));
                String[] p = in.split(",");
                int r = Integer.parseInt(p[0].trim());
                int g = Integer.parseInt(p[1].trim());
                int b = Integer.parseInt(p[2].trim());
                int a = p.length > 3 ? Math.round(Float.parseFloat(p[3].trim()) * 255f) : 255;
                return Color.argb(a, r, g, b);
            }
        } catch (Exception e) {
        }
        return def;
    }

    /* ---------- drawing ---------- */

    private static Paint paint() {
        Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        p.setFilterBitmap(true);
        return p;
    }

    private static Bitmap bg(Theme t) {
        int w = 400, h = 160;
        Bitmap b = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888);
        Canvas cv = new Canvas(b);
        Paint p = paint();
        p.setShader(new LinearGradient(0, 0, w, h, t.bg1, t.bg2, Shader.TileMode.CLAMP));
        cv.drawRoundRect(new RectF(0, 0, w, h), 30, 30, p);
        Paint s = paint();
        s.setStyle(Paint.Style.STROKE);
        s.setStrokeWidth(2);
        s.setColor(t.line);
        cv.drawRoundRect(new RectF(1, 1, w - 1, h - 1), 29, 29, s);
        return b;
    }

    private static Bitmap logo(Context c, Theme t, String key, String name) {
        int s = 120;
        Bitmap out = Bitmap.createBitmap(s, s, Bitmap.Config.ARGB_8888);
        Canvas cv = new Canvas(out);
        Bitmap src = null;
        try {
            File f = new File(new File(c.getFilesDir(), "logos"), PlayerService.safe(key) + ".png");
            if (f.exists()) src = BitmapFactory.decodeFile(f.getAbsolutePath());
        } catch (Throwable e) {
        }
        float r = s / 2f - 4;
        Paint p = paint();
        if (src != null) {
            Bitmap sc = Bitmap.createScaledBitmap(src, s, s, true);
            p.setShader(new BitmapShader(sc, Shader.TileMode.CLAMP, Shader.TileMode.CLAMP));
            cv.drawCircle(s / 2f, s / 2f, r, p);
        } else {
            p.setShader(new LinearGradient(0, 0, s, s, t.d1, t.d2, Shader.TileMode.CLAMP));
            cv.drawCircle(s / 2f, s / 2f, r, p);
            Paint tx = paint();
            tx.setColor(t.dt);
            tx.setTextAlign(Paint.Align.CENTER);
            tx.setTypeface(Typeface.DEFAULT_BOLD);
            tx.setTextSize(s * 0.42f);
            String ch = name == null || name.length() == 0 ? "N" : name.substring(0, name.offsetByCodePoints(0, 1)).toUpperCase();
            cv.drawText(ch, s / 2f, s / 2f + tx.getTextSize() * 0.35f, tx);
        }
        Paint ring = paint();
        ring.setStyle(Paint.Style.STROKE);
        ring.setStrokeWidth(4);
        ring.setColor(t.line);
        cv.drawCircle(s / 2f, s / 2f, r, ring);
        return out;
    }

    private static Bitmap chip(Theme t, int kind) {
        int s = 100;
        Bitmap b = Bitmap.createBitmap(s, s, Bitmap.Config.ARGB_8888);
        Canvas cv = new Canvas(b);
        Paint p = paint();
        p.setColor(t.chip);
        cv.drawCircle(s / 2f, s / 2f, s / 2f - 2, p);
        Paint ip = paint();
        ip.setColor(kind == 2 ? t.mut : t.ink);
        float sc = (s * 0.44f) / 24f;
        cv.save();
        cv.translate(s / 2f - 12 * sc, s / 2f - 12 * sc);
        cv.scale(sc, sc);
        if (kind == 0) {
            cv.drawRect(6, 5, 8, 19, ip);
            Path q = new Path();
            q.moveTo(20, 5);
            q.lineTo(20, 19);
            q.lineTo(9.5f, 12);
            q.close();
            cv.drawPath(q, ip);
        } else if (kind == 1) {
            cv.drawRect(16, 5, 18, 19, ip);
            Path q = new Path();
            q.moveTo(4, 5);
            q.lineTo(4, 19);
            q.lineTo(14.5f, 12);
            q.close();
            cv.drawPath(q, ip);
        } else {
            ip.setStyle(Paint.Style.STROKE);
            ip.setStrokeWidth(2.4f);
            ip.setStrokeCap(Paint.Cap.ROUND);
            cv.drawLine(6, 6, 18, 18, ip);
            cv.drawLine(18, 6, 6, 18, ip);
        }
        cv.restore();
        return b;
    }

    private static Bitmap disc(Theme t, boolean playing) {
        int s = 180;
        Bitmap b = Bitmap.createBitmap(s, s, Bitmap.Config.ARGB_8888);
        Canvas cv = new Canvas(b);
        float cx = s / 2f, cy = s / 2f, R = s / 2f - 4;
        float u = s / 100f;

        Paint shadow = paint();
        shadow.setColor(0x33000000);
        cv.drawCircle(cx, cy + 2, R + 1, shadow);

        int[] cols = new int[9];
        for (int i = 0; i < 9; i++) cols[i] = (i % 2 == 0) ? t.d1 : t.d2;
        Paint d = paint();
        SweepGradient sg = new SweepGradient(cx, cy, cols, null);
        d.setShader(sg);
        cv.save();
        cv.rotate(30, cx, cy);
        cv.drawCircle(cx, cy, R, d);
        cv.restore();

        Paint ring = paint();
        ring.setStyle(Paint.Style.STROKE);
        ring.setStrokeWidth(2 * u * 0.5f + 1);
        ring.setColor(0x59FFFFFF);
        cv.drawCircle(cx, cy, R - 1.5f, ring);
        ring.setColor(t.line);
        ring.setStrokeWidth(3);
        cv.drawCircle(cx, cy, R + 1, ring);

        Paint thin = paint();
        thin.setStyle(Paint.Style.STROKE);
        thin.setStrokeWidth(Math.max(1f, u));
        thin.setColor((t.dt & 0x00FFFFFF) | 0x59000000);
        cv.drawCircle(cx, cy, 46 * u * (R / (s / 2f)), thin);
        cv.drawCircle(cx, cy, 23 * u * (R / (s / 2f)), thin);

        Paint tx = paint();
        tx.setColor(t.dt);
        tx.setTypeface(Typeface.DEFAULT_BOLD);
        tx.setTextAlign(Paint.Align.LEFT);
        float k = R / (s / 2f);
        Path top = new Path();
        float r1 = 29 * u * k;
        top.addArc(new RectF(cx - r1, cy - r1, cx + r1, cy + r1), 180, 180);
        tx.setTextSize(12.5f * u * k);
        cv.drawTextOnPath("Ganeshgpn", top, ((float) Math.PI * r1 - tx.measureText("Ganeshgpn")) / 2f, 0, tx);
        Path bot = new Path();
        float r2 = 39 * u * k;
        bot.addArc(new RectF(cx - r2, cy - r2, cx + r2, cy + r2), 180, -180);
        tx.setTextSize(10.5f * u * k);
        cv.drawTextOnPath("Info Service", bot, ((float) Math.PI * r2 - tx.measureText("Info Service")) / 2f, 0, tx);

        Paint gloss = paint();
        gloss.setShader(new RadialGradient(cx * 0.56f, cy * 0.44f, R * 0.84f,
                new int[]{0x6BFFFFFF, 0x00FFFFFF}, null, Shader.TileMode.CLAMP));
        cv.drawCircle(cx, cy, R, gloss);

        float hr = s * 0.19f;
        Paint hub = paint();
        hub.setColor(t.hub);
        cv.drawCircle(cx, cy, hr, hub);
        Paint hr2 = paint();
        hr2.setStyle(Paint.Style.STROKE);
        hr2.setStrokeWidth(3);
        hr2.setColor(0x99FFFFFF);
        cv.drawCircle(cx, cy, hr, hr2);

        Paint ip = paint();
        ip.setColor(t.hubi);
        float sc = (s * 0.2f) / 24f;
        cv.save();
        cv.translate(cx - 12 * sc, cy - 12 * sc);
        cv.scale(sc, sc);
        if (playing) {
            cv.drawRect(7, 5, 11, 19, ip);
            cv.drawRect(13, 5, 17, 19, ip);
        } else {
            Path q = new Path();
            q.moveTo(8.5f, 5);
            q.lineTo(8.5f, 19);
            q.lineTo(19.5f, 12);
            q.close();
            cv.drawPath(q, ip);
        }
        cv.restore();
        return b;
    }
}
''',
'android/app/src/main/res/drawable/ic_stat_radio.xml': r'''<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="24dp"
    android:height="24dp"
    android:viewportWidth="24"
    android:viewportHeight="24">
    <path
        android:fillColor="#FFFFFFFF"
        android:pathData="M3.24,6.15C2.51,6.43 2,7.17 2,8v12c0,1.1 0.89,2 2,2h16c1.11,0 2,-0.9 2,-2V8c0,-1.11 -0.89,-2 -2,-2H8.3l8.26,-3.34L15.88,1 3.24,6.15zM7,20c-1.66,0 -3,-1.34 -3,-3s1.34,-3 3,-3 3,1.34 3,3 -1.34,3 -3,3zM20,12h-2v-2h-2v2H4V8h16v4z" />
</vector>
''',
'android/app/src/main/res/layout/widget_player.xml': r'''<?xml version="1.0" encoding="utf-8"?>
<FrameLayout xmlns:android="http://schemas.android.com/apk/res/android"
    android:layout_width="match_parent"
    android:layout_height="match_parent">

    <ImageView
        android:id="@+id/w_bg"
        android:layout_width="match_parent"
        android:layout_height="match_parent"
        android:scaleType="fitXY"
        android:contentDescription="@null" />

    <LinearLayout
        android:layout_width="match_parent"
        android:layout_height="match_parent"
        android:orientation="vertical"
        android:paddingLeft="10dp"
        android:paddingTop="8dp"
        android:paddingRight="10dp"
        android:paddingBottom="8dp">

        <LinearLayout
            android:layout_width="match_parent"
            android:layout_height="0dp"
            android:layout_weight="1"
            android:gravity="center_vertical"
            android:orientation="horizontal">

            <ImageView
                android:id="@+id/w_logo"
                android:layout_width="40dp"
                android:layout_height="40dp"
                android:contentDescription="@null"
                android:scaleType="fitCenter" />

            <LinearLayout
                android:id="@+id/w_text"
                android:layout_width="0dp"
                android:layout_height="wrap_content"
                android:layout_marginLeft="10dp"
                android:layout_weight="1"
                android:orientation="vertical">

                <TextView
                    android:id="@+id/w_title"
                    android:layout_width="match_parent"
                    android:layout_height="wrap_content"
                    android:ellipsize="end"
                    android:maxLines="1"
                    android:textSize="15sp"
                    android:textStyle="bold" />

                <TextView
                    android:id="@+id/w_sub"
                    android:layout_width="match_parent"
                    android:layout_height="wrap_content"
                    android:ellipsize="end"
                    android:maxLines="1"
                    android:textSize="12sp" />
            </LinearLayout>

            <ImageView
                android:id="@+id/w_stop"
                android:layout_width="32dp"
                android:layout_height="32dp"
                android:contentDescription="@string/w_stop"
                android:scaleType="fitCenter" />
        </LinearLayout>

        <LinearLayout
            android:layout_width="match_parent"
            android:layout_height="wrap_content"
            android:gravity="center"
            android:orientation="horizontal">

            <ImageView
                android:id="@+id/w_prev"
                android:layout_width="38dp"
                android:layout_height="38dp"
                android:contentDescription="@string/w_prev"
                android:scaleType="fitCenter" />

            <ImageView
                android:id="@+id/w_disc"
                android:layout_width="50dp"
                android:layout_height="50dp"
                android:layout_marginLeft="16dp"
                android:layout_marginRight="16dp"
                android:contentDescription="@string/w_play"
                android:scaleType="fitCenter" />

            <ImageView
                android:id="@+id/w_next"
                android:layout_width="38dp"
                android:layout_height="38dp"
                android:contentDescription="@string/w_next"
                android:scaleType="fitCenter" />
        </LinearLayout>
    </LinearLayout>
</FrameLayout>
''',
'android/app/src/main/res/values/nr_strings.xml': r'''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="widget_desc">नेपाली रेडियोको मिनी प्लेयर</string>
    <string name="w_prev">अघिल्लो रेडियो</string>
    <string name="w_next">अर्को रेडियो</string>
    <string name="w_play">बजाउनुहोस् / रोक्नुहोस्</string>
    <string name="w_stop">बन्द</string>
</resources>
''',
'android/app/src/main/res/xml/radio_widget_info.xml': r'''<?xml version="1.0" encoding="utf-8"?>
<appwidget-provider xmlns:android="http://schemas.android.com/apk/res/android"
    android:description="@string/widget_desc"
    android:initialLayout="@layout/widget_player"
    android:minWidth="250dp"
    android:minHeight="110dp"
    android:minResizeWidth="180dp"
    android:minResizeHeight="90dp"
    android:resizeMode="horizontal|vertical"
    android:targetCellWidth="4"
    android:targetCellHeight="2"
    android:updatePeriodMillis="0"
    android:widgetCategory="home_screen" />
''',
}

def write_files():
    for path, text in FILES.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        print('wrote', path)

def patch_manifest():
    p = 'android/app/src/main/AndroidManifest.xml'
    s = open(p, encoding='utf-8').read()
    if 'PlayerService' in s:
        print('manifest already patched'); return
    if 'usesCleartextTraffic' not in s:
        s = s.replace('<application', '<application\n        android:usesCleartextTraffic="true"', 1)
    comp = """
        <receiver android:name=".RadioWidgetProvider" android:exported="true">
            <intent-filter>
                <action android:name="android.appwidget.action.APPWIDGET_UPDATE" />
            </intent-filter>
            <meta-data android:name="android.appwidget.provider" android:resource="@xml/radio_widget_info" />
        </receiver>
        <service android:name=".PlayerService" android:exported="false" android:foregroundServiceType="mediaPlayback" />
    </application>"""
    assert '</application>' in s
    s = s.replace('</application>', comp, 1)
    perms = ['FOREGROUND_SERVICE', 'FOREGROUND_SERVICE_MEDIA_PLAYBACK', 'POST_NOTIFICATIONS', 'WAKE_LOCK', 'ACCESS_WIFI_STATE', 'ACCESS_NETWORK_STATE']
    add = ''.join('\n    <uses-permission android:name="android.permission.%s" />' % x for x in perms if x not in s)
    s = s.replace('</manifest>', add + '\n</manifest>', 1)
    open(p, 'w', encoding='utf-8').write(s)
    print('manifest patched')

def patch_gradle():
    p = 'android/app/build.gradle'
    s = open(p, encoding='utf-8').read()
    if 'media3-exoplayer' in s:
        print('gradle already patched'); return
    deps = ('dependencies {\n'
            '    implementation "androidx.media3:media3-exoplayer:1.3.1"\n'
            '    implementation "androidx.media3:media3-exoplayer-hls:1.3.1"\n'
            '    implementation "androidx.media3:media3-datasource:1.3.1"\n')
    assert 'dependencies {' in s
    s = s.replace('dependencies {\n', deps, 1)
    open(p, 'w', encoding='utf-8').write(s)
    print('gradle patched')

if __name__ == '__main__':
    write_files()
    patch_manifest()
    patch_gradle()
    print('native setup done')
