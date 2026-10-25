import { useEffect, useRef } from "react";
import { countUp } from "../lib/anim";

/** A number that counts up when it first appears (and when it changes). */
export function Count({ value, className }: { value: number; className?: string }) {
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    countUp(ref.current, value);
  }, [value]);

  return (
    <b ref={ref as React.RefObject<HTMLElement>} className={className}>
      {value}
    </b>
  );
}
