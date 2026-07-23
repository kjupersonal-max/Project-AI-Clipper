"use client";

import { memo, useEffect, useRef, useState } from "react";
import type { CaptionSegment } from "@/lib/clip-captions";
import { findActiveCaption } from "@/lib/clip-captions";
import {
  applyTextTransform,
  buildCaptionStyleCss,
  getCaptionAnimationClassName,
  resolveCaptionDisplayState,
  type CaptionSafeAreaMode,
  type CaptionStyle,
} from "@/lib/caption-style";
import { cn } from "@/lib/utils";

type CaptionPreviewOverlayProps = {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  segments: CaptionSegment[];
  style: CaptionStyle;
  showSafeAreaGuides?: boolean;
};

type SafeAreaGuideProps = {
  mode: CaptionSafeAreaMode;
};

function SafeAreaGuides({ mode }: SafeAreaGuideProps) {
  if (mode === "none") {
    return null;
  }

  const label =
    mode === "tiktok"
      ? "TikTok preview guide"
      : mode === "youtube-shorts"
        ? "YouTube Shorts preview guide"
        : "Safe area preview guide";

  return (
    <>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[12%] border-b border-dashed border-yellow-400/40 bg-yellow-400/5"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 bottom-0 h-[22%] border-t border-dashed border-yellow-400/40 bg-yellow-400/5"
      />
      {mode === "generic" ? (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-[12%_8%_22%_8%] rounded border border-dashed border-emerald-400/50"
        />
      ) : null}
      <div className="pointer-events-none absolute left-2 top-2 rounded bg-black/60 px-2 py-0.5 text-[10px] text-yellow-200">
        {label}
      </div>
    </>
  );
}

function CaptionPreviewOverlayInner({
  videoRef,
  segments,
  style,
  showSafeAreaGuides = false,
}: CaptionPreviewOverlayProps) {
  const [currentTime, setCurrentTime] = useState(0);
  const [reducedMotion, setReducedMotion] = useState(() => {
    if (typeof window.matchMedia !== "function") {
      return false;
    }
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  });
  const [animationKey, setAnimationKey] = useState(0);
  const previousGroupKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") {
      return;
    }

    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");

    function handleChange(event: MediaQueryListEvent) {
      setReducedMotion(event.matches);
    }

    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) {
      return;
    }

    let frameId = 0;

    function tick() {
      if (video) {
        setCurrentTime(video.currentTime);
      }
      frameId = window.requestAnimationFrame(tick);
    }

    function handleTimeUpdate() {
      if (video) {
        setCurrentTime(video.currentTime);
      }
    }

    video.addEventListener("timeupdate", handleTimeUpdate);
    video.addEventListener("seeked", handleTimeUpdate);
    frameId = window.requestAnimationFrame(tick);

    return () => {
      video.removeEventListener("timeupdate", handleTimeUpdate);
      video.removeEventListener("seeked", handleTimeUpdate);
      window.cancelAnimationFrame(frameId);
    };
  }, [videoRef]);

  const activeSegment = findActiveCaption(segments, currentTime);
  const displayState = activeSegment
    ? resolveCaptionDisplayState(activeSegment, currentTime, style.words_per_group)
    : null;

  const groupKey = displayState
    ? `${displayState.segment.id}-${displayState.group?.start ?? displayState.segment.start}`
    : null;

  useEffect(() => {
    if (groupKey !== previousGroupKeyRef.current) {
      previousGroupKeyRef.current = groupKey;
      setAnimationKey((value) => value + 1);
    }
  }, [groupKey]);

  const animationClass = getCaptionAnimationClassName(
    style.animation_type,
    style.animation_intensity,
    reducedMotion,
  );

  const containerStyle: React.CSSProperties = {
    left: `${style.horizontal_position}%`,
    top: `${style.vertical_position}%`,
    transform: "translate(-50%, -50%)",
    width: `${style.max_line_width}%`,
    textAlign: style.text_alignment,
  };

  const captionCss = buildCaptionStyleCss(style);

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {showSafeAreaGuides && style.safe_area_mode !== "none" ? (
        <SafeAreaGuides mode={style.safe_area_mode} />
      ) : null}

      {displayState ? (
        <div className="absolute" style={containerStyle}>
          <div
            key={animationKey}
            className={cn("inline-block rounded px-3 py-2", animationClass)}
            style={{
              ...captionCss,
              display: "inline-block",
            }}
          >
            {displayState.group && displayState.group.words.length > 0 ? (
              <span>
                {displayState.group.words.map((word, index) => {
                  const isActive = displayState.activeWordIndex === index;
                  const wordText = applyTextTransform(word.word, style.text_transform);
                  const showEmphasis =
                    style.animation_type === "active-word-emphasis" && isActive && !reducedMotion;

                  return (
                    <span key={`${word.word}-${word.start}-${index}`}>
                      <span
                        className={cn(
                          "transition-colors duration-100",
                          showEmphasis ? "caption-active-word-emphasis" : undefined,
                        )}
                        style={{
                          color: isActive ? style.active_word_color : style.text_color,
                          transform: showEmphasis ? "scale(1.08)" : undefined,
                          display: "inline-block",
                        }}
                      >
                        {wordText}
                      </span>
                      {index < displayState.group!.words.length - 1 ? " " : ""}
                    </span>
                  );
                })}
              </span>
            ) : (
              <span>{applyTextTransform(displayState.displayText, style.text_transform)}</span>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export const CaptionPreviewOverlay = memo(CaptionPreviewOverlayInner);
