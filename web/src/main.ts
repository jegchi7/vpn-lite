import { mount } from "svelte";
import App from "./App.svelte";
import "./app.css";
import type { Boot } from "./types";

const source = document.getElementById("chimera-data");
const target = document.getElementById("app");
if (source && target) {
  const boot: Boot = JSON.parse(source.textContent || "{}");
  mount(App, { target, props: { boot } });
}
