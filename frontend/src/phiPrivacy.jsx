import React, { createContext, useContext, useState } from "react";
import { HIDE_PHI_KEY } from "./utils/phi.js";

const PhiPrivacyContext = createContext({
  hidePhi: false,
  setHidePhi: () => {},
});

/** Shared Hide PHI switch. Default off. Isolated tests that skip the
 * provider keep seeing PHI (the default context), matching production's
 * default-off. */
export function PhiPrivacyProvider({ children }) {
  const [hidePhi, setHidePhiState] = useState(
    () => localStorage.getItem(HIDE_PHI_KEY) === "1",
  );

  const setHidePhi = (next) => {
    setHidePhiState(next);
    localStorage.setItem(HIDE_PHI_KEY, next ? "1" : "0");
  };

  return (
    <PhiPrivacyContext.Provider value={{ hidePhi, setHidePhi }}>
      {children}
    </PhiPrivacyContext.Provider>
  );
}

export function usePhiPrivacy() {
  return useContext(PhiPrivacyContext);
}
