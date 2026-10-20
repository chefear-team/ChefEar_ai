// API_CONTRACT.md 와 같은 모양. 계약을 바꾸면 여기도 같이 고친다.

export type Screen =
  | "start"
  | "recipe_confirm"
  | "cooking_step"
  | "cooking_complete"
  | "unclassified"
  | "register_dish_name"
  | "register_ingredients"
  | "register_steps"
  | "complete"
  | "login_required"
  | "my_recipes"
  | "edit_recipe";

export interface Speech {
  text: string;
  audio_url: string | null;
}

export interface ChatMessage {
  role: "user" | "ai";
  text: string;
}

export interface RecipeStep {
  step_number: number;
  text: string;
}

export interface RecipeView {
  recipe_id: string;
  dish_name: string;
  ingredients: string[];
  steps: RecipeStep[];
  step_number: number;
  total: number;
}

export interface Registration {
  dish_name: string | null;
  ingredients: string[];
  instructions: string[];
  guess: string | null;
}

export interface State {
  session_id: string;
  screen: Screen;
  logged_in: boolean;
  transcript: string | null;
  speech: Speech | null;
  notice: string | null;
  chat: ChatMessage[];
  recipe: RecipeView | null;
  registration: Registration | null;
}

export type Action =
  | { type: "nav"; name: "이전" | "다시" | "다음" }
  | { type: "goto_step"; step_number: number }
  | { type: "start_cooking" }
  | { type: "other_recipe" }
  | { type: "home" }
  | { type: "register_start" }
  | { type: "register_dish_name"; value: string }
  | { type: "register_add_ingredients"; items: string[] }
  | { type: "register_ingredients_done" }
  | { type: "register_add_step"; text: string }
  | { type: "register_edit_step"; index: number; text: string }
  | { type: "register_delete_step"; index: number }
  | { type: "register_save" }
  | { type: "cancel" };

export interface MyRecipeSummary {
  recipe_id: string;
  dish_name: string;
  created_at: string;
  audio_ready: boolean;
}

export interface MyRecipeDetail {
  recipe_id: string;
  dish_name: string;
  ingredients: string[];
  instructions: string[];
}

export interface MyRecipeInput {
  dish_name: string;
  ingredients: string[];
  instructions: string[];
}

export interface Api {
  warmup(): Promise<void>;
  createSession(): Promise<State>;
  getSession(id: string): Promise<State>;
  utteranceText(id: string, text: string): Promise<State>;
  utteranceAudio(id: string, wav: Blob): Promise<State>;
  action(id: string, action: Action): Promise<State>;
  tts(text: string): Promise<Blob>;
  listMyRecipes(): Promise<MyRecipeSummary[]>;
  getMyRecipe(id: string): Promise<MyRecipeDetail>;
  updateMyRecipe(id: string, body: MyRecipeInput): Promise<MyRecipeDetail>;
  deleteMyRecipe(id: string): Promise<void>;
}
