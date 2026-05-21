import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { useWebSocket } from "./useWebSocket";
import "./index.css";

function Root() {
  useWebSocket();
  return <App />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
