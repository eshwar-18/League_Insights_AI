"use client";

import { useEffect } from "react";
import "./SummonersRiftBG.css";

export default function SummonersRiftBG() {
  useEffect(() => {
    if (typeof document === "undefined") return;

    const apply = () => {
      document.documentElement.classList.toggle("paused", document.hidden);
    };

    apply();
    document.addEventListener("visibilitychange", apply);
    return () => document.removeEventListener("visibilitychange", apply);
  }, []);

  return (
    <>
      <div className="bg" aria-hidden="true" />
      <div className="glow" aria-hidden="true" />
      <div className="vignette" aria-hidden="true" />
    </>
  );
}
