import React from "react";
import ReactDOM from "react-dom/client";
// The family's three typefaces, self-hosted (no Google Fonts request).
import "@fontsource-variable/fraunces/full.css";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
// The app's palette first (identity/tokens.css), then the family's shared styles.
import "@identity/tokens.css";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
