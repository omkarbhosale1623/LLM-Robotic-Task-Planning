"use client";

import { useMemo, type ReactNode } from "react";

import type { WorldState } from "@/lib/types";
import { colorHex } from "@/lib/utils";

interface SceneVisualiserProps {
  world: WorldState | null;
  highlightId?: string | null;
}

// World coordinates are roughly x in [-0.6, 0.6], y in [-0.45, 0.45]. We map
// them into an SVG viewbox with the origin centred and the y-axis flipped so
// "up" on the table (positive y) renders towards the top of the canvas.
const VIEW_W = 640;
const VIEW_H = 420;
const SCALE = 460; // px per world unit
const CX = VIEW_W / 2;
const CY = VIEW_H / 2;

function toScreen(x: number, y: number): { sx: number; sy: number } {
  return { sx: CX + x * SCALE, sy: CY - y * SCALE };
}

/**
 * Top-down SVG visualiser of the tabletop: locations, colored object shapes,
 * and the robot/gripper. Re-renders whenever `world` changes, so it animates as
 * execution events stream in.
 */
export function SceneVisualiser({ world, highlightId }: SceneVisualiserProps) {
  const robotScreen = useMemo(
    () => (world ? toScreen(world.robot.pose.x, world.robot.pose.y) : null),
    [world],
  );

  if (!world) {
    return (
      <div className="flex h-[420px] items-center justify-center text-sm text-slate-500">
        Loading scene…
      </div>
    );
  }

  return (
    <svg
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      className="h-auto w-full rounded-lg bg-[#0b1220]"
      role="img"
      aria-label="Tabletop scene"
    >
      <defs>
        <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">
          <path d="M32 0H0V32" fill="none" stroke="#16233b" strokeWidth="1" />
        </pattern>
      </defs>
      <rect width={VIEW_W} height={VIEW_H} fill="url(#grid)" />

      {/* Locations */}
      {world.locations.map((loc) => {
        const { sx, sy } = toScreen(loc.anchor.x, loc.anchor.y);
        const w = loc.width * SCALE;
        const h = loc.height * SCALE;
        const isContainer = loc.kind === "container";
        const isZone = loc.kind === "zone";
        const isTable = loc.id === "table";
        return (
          <g key={loc.id} opacity={isTable ? 0.5 : 1}>
            <rect
              x={sx - w / 2}
              y={sy - h / 2}
              width={w}
              height={h}
              rx={isContainer ? 10 : 6}
              fill={
                isContainer
                  ? "rgba(148,163,184,0.10)"
                  : isZone
                    ? "rgba(56,189,248,0.06)"
                    : "rgba(30,41,59,0.45)"
              }
              stroke={
                isContainer ? "#64748b" : isZone ? "#38bdf8" : "#334155"
              }
              strokeWidth={1.5}
              strokeDasharray={isZone ? "6 5" : undefined}
            />
            {!isTable && (
              <text
                x={sx}
                y={sy - h / 2 - 6}
                textAnchor="middle"
                className="fill-slate-400"
                fontSize={12}
              >
                {loc.name}
              </text>
            )}
          </g>
        );
      })}

      {/* Objects */}
      {world.objects.map((obj) => {
        const { sx, sy } = toScreen(obj.position.x, obj.position.y);
        const size = obj.size * SCALE;
        const fill = colorHex(obj.color);
        const held = world.robot.holding === obj.id;
        const highlighted = highlightId === obj.id;
        const stroke = highlighted ? "#fde047" : held ? "#ffffff" : "rgba(0,0,0,0.35)";
        const strokeWidth = highlighted || held ? 3 : 1.5;

        let shapeEl: ReactNode;
        if (obj.shape === "ball") {
          shapeEl = (
            <circle cx={sx} cy={sy} r={size / 2} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
          );
        } else if (obj.shape === "cup" || obj.shape === "bowl") {
          shapeEl = (
            <path
              d={`M ${sx - size / 2} ${sy - size / 2}
                  L ${sx + size / 2} ${sy - size / 2}
                  L ${sx + size / 2.6} ${sy + size / 2}
                  L ${sx - size / 2.6} ${sy + size / 2} Z`}
              fill={fill}
              stroke={stroke}
              strokeWidth={strokeWidth}
            />
          );
        } else {
          shapeEl = (
            <rect
              x={sx - size / 2}
              y={sy - size / 2}
              width={size}
              height={size}
              rx={4}
              fill={fill}
              stroke={stroke}
              strokeWidth={strokeWidth}
            />
          );
        }

        return (
          <g key={obj.id} className="animate-fade-in">
            {held && (
              <circle
                cx={sx}
                cy={sy}
                r={size / 1.4}
                fill="none"
                stroke="#ffffff"
                strokeWidth={1}
                opacity={0.5}
                className="animate-pulse-ring"
              />
            )}
            {shapeEl}
            <text
              x={sx}
              y={sy + size / 2 + 12}
              textAnchor="middle"
              className="fill-slate-300"
              fontSize={10}
            >
              {obj.id}
            </text>
          </g>
        );
      })}

      {/* Robot gripper */}
      {robotScreen && (
        <g>
          <line
            x1={CX}
            y1={VIEW_H - 8}
            x2={robotScreen.sx}
            y2={robotScreen.sy}
            stroke="#475569"
            strokeWidth={4}
            strokeLinecap="round"
          />
          <g transform={`translate(${robotScreen.sx}, ${robotScreen.sy})`}>
            <circle r={14} fill="#1e293b" stroke="#38bdf8" strokeWidth={2} />
            {/* Gripper fingers — open or closed */}
            <line
              x1={world.robot.gripper_open ? -11 : -5}
              y1={-13}
              x2={world.robot.gripper_open ? -11 : -5}
              y2={-22}
              stroke="#38bdf8"
              strokeWidth={3}
              strokeLinecap="round"
            />
            <line
              x1={world.robot.gripper_open ? 11 : 5}
              y1={-13}
              x2={world.robot.gripper_open ? 11 : 5}
              y2={-22}
              stroke="#38bdf8"
              strokeWidth={3}
              strokeLinecap="round"
            />
          </g>
          <text
            x={robotScreen.sx}
            y={robotScreen.sy + 28}
            textAnchor="middle"
            fontSize={10}
            className="fill-accent"
          >
            {world.robot.holding ? `holding ${world.robot.holding}` : "gripper"}
          </text>
        </g>
      )}
    </svg>
  );
}
