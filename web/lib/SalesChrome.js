"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";

const SalesChromeContext = createContext({
  command: null,
  setCommand: () => {},
  clearCommand: () => {},
});

export function SalesChromeProvider({ children }) {
  const [command, setCommandState] = useState(null);
  const setCommand = useCallback((next) => {
    setCommandState(next);
  }, []);
  const clearCommand = useCallback(() => setCommandState(null), []);
  const value = useMemo(
    () => ({ command, setCommand, clearCommand }),
    [command, setCommand, clearCommand],
  );
  return (
    <SalesChromeContext.Provider value={value}>
      {children}
    </SalesChromeContext.Provider>
  );
}

export function useSalesChrome() {
  return useContext(SalesChromeContext);
}
