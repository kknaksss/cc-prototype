// 통역 세션(SPEC §7 · interpret-ws-contract.md) — 마이크 → PCM 16k → WS, 자막 · 번역 음성 받기.
// 화면 상태는 콜백으로만 알린다(컴포넌트가 setState).
import { openInterpretSocket } from './api';

export type InterpState = 'connecting' | 'listening' | 'paused' | 'error';
export type InterpErrorKind = 'mic' | 'server' | 'closed';

export interface Caption {
  key: string; // 세션 번호 + 발화 id — 언어를 바꿔 다시 붙어도 겹치지 않게
  side: 'me' | 'them';
  original: string;
  translation: string;
  final: boolean;
}

export interface InterpCallbacks {
  onState: (s: InterpState) => void;
  onCaption: (c: Caption) => void;
  onError: (kind: InterpErrorKind, message: string) => void;
}

// 마이크 입력(컨텍스트 샘플레이트)을 16kHz mono s16le 로 바꿔 40ms(640샘플) 조각으로 보낸다
const WORKLET = `
class Pcm16kWriter extends AudioWorkletProcessor {
  constructor() { super(); this.ratio = sampleRate / 16000; this.pos = 0; this.buf = new Int16Array(640); this.n = 0; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    let pos = this.pos;
    while (pos < ch.length) {
      const i = Math.floor(pos), f = pos - i;
      const a = ch[i], b = i + 1 < ch.length ? ch[i + 1] : a;
      const v = Math.max(-1, Math.min(1, a + (b - a) * f));
      this.buf[this.n++] = v < 0 ? v * 0x8000 : v * 0x7fff;
      if (this.n === this.buf.length) { this.port.postMessage(this.buf.buffer, [this.buf.buffer]); this.buf = new Int16Array(640); this.n = 0; }
      pos += this.ratio;
    }
    this.pos = pos - ch.length;
    return true;
  }
}
registerProcessor('pcm16k-writer', Pcm16kWriter);
`;

let sessionSeq = 0;

export class InterpretSession {
  private ws: WebSocket | null = null;
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private state: InterpState = 'connecting';
  private closed = false;
  private readonly seq = ++sessionSeq;
  // 번역 음성 재생
  private outRate = 24000;
  private outFormat = 'pcm_s16le';
  private nextTime = 0;
  private carry: Uint8Array | null = null; // 조각 경계에 걸친 1바이트
  private encoded: ArrayBuffer[] = []; // pcm 이 아닌 형식이면 audio_end 에서 한 번에 디코드

  constructor(
    private readonly opts: { scheduleId: string; lang: string; traditional: boolean },
    private readonly cb: InterpCallbacks,
  ) {}

  async start() {
    this.set('connecting');
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch {
      this.fail('mic', '브라우저가 마이크 사용을 막고 있어요. 주소창 왼쪽 자물쇠 → 마이크 → 허용으로 바꿔 주세요.');
      return;
    }
    if (this.closed) return this.release();
    try {
      this.ctx = new AudioContext();
      // 클릭 뒤 비동기로 만든 컨텍스트는 멈춰 있을 수 있다 — 번역 음성이 나오게 깨운다
      if (this.ctx.state === 'suspended') await this.ctx.resume().catch(() => undefined);
      const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }));
      await this.ctx.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);
      if (this.closed) return this.release();
      const src = this.ctx.createMediaStreamSource(this.stream);
      this.node = new AudioWorkletNode(this.ctx, 'pcm16k-writer');
      this.node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
        if (this.state === 'listening' && this.ws?.readyState === WebSocket.OPEN) this.ws.send(e.data);
      };
      src.connect(this.node);
    } catch {
      this.fail('mic', '이 브라우저에서 마이크 소리를 처리하지 못했어요.');
      return;
    }
    this.connect();
  }

  private connect() {
    const ws = openInterpretSocket();
    this.ws = ws;
    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          type: 'start',
          lang: this.opts.lang,
          scheduleId: this.opts.scheduleId,
          traditional: this.opts.traditional,
        }),
      );
    };
    ws.onmessage = (e: MessageEvent<string | ArrayBuffer>) => {
      if (typeof e.data === 'string') this.onText(e.data);
      else this.onAudio(e.data);
    };
    ws.onclose = () => {
      if (!this.closed && this.state !== 'error') this.fail('closed', '통역 서버와 연결이 끊겼어요.');
    };
  }

  private onText(raw: string) {
    let m: Record<string, unknown>;
    try {
      m = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return;
    }
    switch (m.type) {
      case 'ready':
        if (this.state === 'connecting') this.set('listening');
        break;
      case 'caption':
        this.cb.onCaption({
          key: this.seq + ':' + String(m.id),
          side: m.side === 'me' ? 'me' : 'them',
          original: String(m.original ?? ''),
          translation: String(m.translation ?? ''),
          final: m.final === true,
        });
        break;
      case 'audio_start':
        this.outRate = typeof m.sampleRate === 'number' ? m.sampleRate : 24000;
        this.outFormat = typeof m.format === 'string' ? m.format : 'pcm_s16le';
        this.carry = null;
        this.encoded = [];
        break;
      case 'audio_end':
        if (this.outFormat !== 'pcm_s16le' && this.encoded.length) void this.playEncoded(this.encoded);
        this.encoded = [];
        this.carry = null;
        break;
      case 'error':
        this.fail('server', String(m.message ?? '통역 서버 오류'));
        break;
    }
  }

  private onAudio(buf: ArrayBuffer) {
    if (!this.ctx || this.closed) return;
    if (this.outFormat !== 'pcm_s16le') {
      this.encoded.push(buf);
      return;
    }
    let bytes = new Uint8Array(buf);
    if (this.carry) {
      const joined = new Uint8Array(this.carry.length + bytes.length);
      joined.set(this.carry);
      joined.set(bytes, this.carry.length);
      bytes = joined;
      this.carry = null;
    }
    if (bytes.length % 2) {
      this.carry = bytes.slice(bytes.length - 1);
      bytes = bytes.slice(0, bytes.length - 1);
    }
    const n = bytes.length / 2;
    if (!n) return;
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const audio = this.ctx.createBuffer(1, n, this.outRate);
    const ch = audio.getChannelData(0);
    for (let i = 0; i < n; i++) ch[i] = view.getInt16(i * 2, true) / 0x8000;
    this.schedule(audio);
  }

  // 조각을 앞 조각 끝에 바로 이어 붙여 재생 — 끊김 없이
  private schedule(audio: AudioBuffer) {
    const ctx = this.ctx!;
    const src = ctx.createBufferSource();
    src.buffer = audio;
    src.connect(ctx.destination);
    const at = Math.max(ctx.currentTime + 0.05, this.nextTime);
    src.start(at);
    this.nextTime = at + audio.duration;
  }

  private async playEncoded(parts: ArrayBuffer[]) {
    if (!this.ctx) return;
    const total = parts.reduce((s, p) => s + p.byteLength, 0);
    const all = new Uint8Array(total);
    let o = 0;
    parts.forEach((p) => {
      all.set(new Uint8Array(p), o);
      o += p.byteLength;
    });
    try {
      this.schedule(await this.ctx.decodeAudioData(all.buffer));
    } catch {
      // 디코드 못 하는 형식이면 자막만 남는다
    }
  }

  // [멈춤]/[다시 듣기] — 연결은 두고 마이크만
  toggle() {
    if (this.state === 'listening') {
      this.send({ type: 'pause' });
      this.stream?.getAudioTracks().forEach((t) => (t.enabled = false));
      this.set('paused');
    } else if (this.state === 'paused') {
      this.stream?.getAudioTracks().forEach((t) => (t.enabled = true));
      this.send({ type: 'resume' });
      this.set('listening');
    }
  }

  // [닫기] — stop 후 WS · 트랙 · AudioContext 모두 정리
  close() {
    if (this.closed) return;
    this.closed = true;
    this.send({ type: 'stop' });
    this.release();
  }

  private release() {
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.onmessage = null;
      if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) this.ws.close();
      this.ws = null;
    }
    this.node?.port.close();
    this.node?.disconnect();
    this.node = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    void this.ctx?.close().catch(() => undefined);
    this.ctx = null;
  }

  private send(m: object) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(m));
  }

  private set(s: InterpState) {
    this.state = s;
    if (!this.closed) this.cb.onState(s);
  }

  private fail(kind: InterpErrorKind, message: string) {
    if (this.closed) return;
    this.set('error');
    this.cb.onError(kind, message);
    // 오류면 더 듣지 않는다 — [다시 시도] 가 새 세션을 연다
    this.closed = true;
    this.release();
  }
}
