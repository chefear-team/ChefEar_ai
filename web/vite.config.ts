import { createReadStream, existsSync } from "node:fs";
import { dirname, extname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const here = dirname(fileURLToPath(import.meta.url));

const MIME: Record<string, string> = {
  ".mjs": "text/javascript",
  ".js": "text/javascript",
  ".wasm": "application/wasm",
  ".onnx": "application/octet-stream",
};

/**
 * 개발 서버 전용. onnxruntime 이 런타임에 `import("/vad/ort-wasm-simd-threaded.mjs")` 로 public 파일을 모듈로 불러오는데,
 * Vite 개발 서버는 "public 파일은 소스에서 import 하면 안 된다"며 오류 팝업을 띄운다.
 * /vad/ 요청은 Vite 의 모듈 변환 단계에 들어가기 전에 파일 그대로 내준다. 운영 빌드에는 영향이 없다(정적 파일로 서빙됨).
 */
function vadDevAssets(): Plugin {
  const dir = join(here, "public", "vad");
  return {
    name: "vad-dev-assets",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use("/vad/", (req, res, next) => {
        const name = decodeURIComponent((req.url ?? "").split("?")[0]).replace(/^\/+/, "");
        const file = join(dir, name);
        if (!name || name.includes("..") || !file.startsWith(dir) || !existsSync(file)) return next();
        res.setHeader("Content-Type", MIME[extname(file)] ?? "application/octet-stream");
        res.setHeader("Cache-Control", "no-cache");
        createReadStream(file).pipe(res);
      });
    },
  };
}

// VAD 정적 자원(silero 모델, worklet, onnx wasm)은 scripts/copy-vad-assets.mjs 가
// public/vad/ 로 복사한다(prebuild/predev 에서 자동 실행).
export default defineConfig({
  plugins: [react(), vadDevAssets()],
  build: { target: "es2020", chunkSizeWarningLimit: 900 },
});
