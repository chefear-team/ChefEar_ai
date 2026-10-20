export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** 서버가 보내는 오류 코드를 화면에 그대로 보여 주지 않고 한글 문구로 바꾼다. */
const SERVER_CODES: Record<string, string> = {
  login_required: "로그인 후에 쓸 수 있어요.",
  stt_unavailable: "음성 인식 서버를 깨우는 중이에요. 잠시 뒤 다시 말씀해 주세요.",
  tts_unavailable: "음성 합성 서버를 깨우는 중이에요. 화면의 글자를 먼저 읽어 주세요.",
  rate_limited: "요청이 너무 많아요. 잠시 후 다시 시도해 주세요.",
  audio_too_large: "말씀이 너무 길어요. 조금 짧게 나눠서 말씀해 주세요.",
  audio_required: "음성이 전달되지 않았어요. 다시 말씀해 주세요.",
  bad_text: "읽어 줄 문장이 올바르지 않아요.",
  invalid_text: "사용할 수 없는 문자가 들어 있어요. 요리와 관련된 글자만 입력해 주세요.",
  text_too_long: "글이 너무 길어요. 조금 줄여 주세요.",
  dish_name_too_long: "요리 이름이 너무 길어요.",
  ingredient_too_long: "재료 이름이 너무 길어요.",
  ingredient_too_many: "재료가 너무 많아요.",
  step_too_long: "한 단계 설명이 너무 길어요.",
  step_too_many: "조리 순서가 너무 많아요.",
  invalid_input: "입력 형식이 올바르지 않아요.",
  too_many_invalid: "올바르지 않은 입력이 너무 많아요. 잠시 후 처음부터 다시 시도해 주세요.",
  payload_too_large: "보내는 내용이 너무 커요.",
  bad_json: "요청 형식이 올바르지 않아요.",
  unknown_action: "지원하지 않는 동작이에요.",
};

export function friendlyServerMessage(code: string): string | null {
  return SERVER_CODES[code] ?? null;
}

export function errorMessage(e: unknown, fallback = "문제가 생겼어요. 다시 시도해 주세요."): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

export function errorStatus(e: unknown): number {
  return e instanceof ApiError ? e.status : 0;
}
