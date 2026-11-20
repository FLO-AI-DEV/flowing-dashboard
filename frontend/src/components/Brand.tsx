/* The FLO logo, recoloured by theme: the transparent navy artwork is used as a mask and filled with --brand
   (navy on light, blush on dark), so the exact letterforms of the logo are kept. */

const SRC = {
  letters: { url: "/brand/flo-letters-navy.png", ratio: 450 / 165 },
  full: { url: "/brand/flo-wordmark-navy.png", ratio: 800 / 566 },
};

export function Wordmark({ variant = "letters", height = 24, className = "", style, wing = false }: { variant?: "letters" | "full"; height?: number; className?: string; style?: React.CSSProperties; wing?: boolean }) {
  const s = SRC[variant];
  if (wing)
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: Math.round(height * 0.25), flex: "none" }} aria-label="FLO WING" role="img">
        <Wordmark variant={variant} height={height} className={className} style={style} />
        <span aria-hidden="true" style={{ color: "var(--brand)", fontFamily: "var(--font-display, inherit)", fontWeight: 600, fontSize: Math.round(height * 0.5), letterSpacing: "0.16em", lineHeight: 1 }}>
          WING
        </span>
      </span>
    );
  return (
    <span
      role="img"
      aria-label="FLO"
      className={className}
      style={{
        display: "inline-block",
        height,
        width: height * s.ratio,
        background: "var(--brand)",
        WebkitMaskImage: `url(${s.url})`,
        maskImage: `url(${s.url})`,
        WebkitMaskSize: "contain",
        maskSize: "contain",
        WebkitMaskRepeat: "no-repeat",
        maskRepeat: "no-repeat",
        WebkitMaskPosition: "center",
        maskPosition: "center",
        flex: "none",
        ...style,
      }}
    />
  );
}

/** The logo's open bracket in its own 1600 x 1131 artwork space: top-right end, top-right corner, top-left corner,
 *  bottom-left corner, bottom end. Stroke 9. */
export const BRACKET = [
  [1474, 264],
  [1474, 136],
  [125, 136],
  [125, 956],
  [295, 956],
] as const;
export const ART = { w: 1600, h: 1131, stroke: 9 };
