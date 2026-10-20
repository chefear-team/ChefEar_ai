// @ricky0123/vad-web 이 런타임에 fetch 하는 파일(worklet, silero onnx, onnxruntime wasm)을
// public/vad/ 로 복사한다. 결과물은 .gitignore 대상이며 build/dev 때마다 다시 만든다.
import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "public", "vad");
mkdirSync(out, { recursive: true });

const vadDist = join(root, "node_modules", "@ricky0123", "vad-web", "dist");
const ortDist = join(root, "node_modules", "onnxruntime-web", "dist");

const files = [
  [vadDist, "vad.worklet.bundle.min.js"],
  [vadDist, "silero_vad_v5.onnx"],
  [ortDist, "ort-wasm-simd-threaded.mjs"],
  [ortDist, "ort-wasm-simd-threaded.wasm"],
];

for (const [dir, name] of files) {
  const src = join(dir, name);
  if (!existsSync(src)) {
    console.error(`[copy-vad-assets] 없음: ${src} (npm install 을 먼저 실행하세요)`);
    process.exit(1);
  }
  cpSync(src, join(out, name));
}
console.log(`[copy-vad-assets] ${files.length}개 파일 -> public/vad/`);
