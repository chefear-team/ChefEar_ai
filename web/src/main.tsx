import { createRoot } from "react-dom/client";
import App from "./App";
import { api } from "./lib/api";
import "./styles.css";

// 콜드 스타트 대비: 페이지가 열리자마자 API(와 STT/TTS 컨테이너)를 깨운다. 기다리지 않는다.
void api.warmup();

createRoot(document.getElementById("root") as HTMLElement).render(<App />);
