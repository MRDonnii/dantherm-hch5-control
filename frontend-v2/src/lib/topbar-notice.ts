import { createContext, useContext } from "react";

export interface TopbarNoticeContextValue {
  notice: string;
  setNotice: (message: string) => void;
}

export const TopbarNoticeContext = createContext<TopbarNoticeContextValue>({
  notice: "",
  setNotice: () => {},
});

export const useTopbarNotice = () => useContext(TopbarNoticeContext);
