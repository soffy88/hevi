'use client';

/**
 * TabBar — 共享 Tab 切换组件
 * 统一 4 个工具台页面的 Tab 样式，消灭手写重复代码。
 *
 * 支持两种视觉风格：
 * - "underline"（默认）: 底部蓝色下划线，适合页内 Tab
 * - "pill": 圆角药丸背景，适合卡片内子 Tab
 */

import React from 'react';

export interface TabItem<T extends string = string> {
  key: T;
  label: string;
  icon?: string;
  badge?: number | string;
}

interface TabBarProps<T extends string = string> {
  items: Array<TabItem<T>>;
  active: T;
  onChange: (key: T) => void;
  variant?: 'underline' | 'pill';
  className?: string;
}

export function TabBar<T extends string>({
  items,
  active,
  onChange,
  variant = 'underline',
  className = '',
}: TabBarProps<T>) {
  if (variant === 'pill') {
    return (
      <div className={`hevi-tabbar hevi-tabbar--pill ${className}`}>
        {items.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`hevi-tabbar__item ${active === item.key ? 'hevi-tabbar__item--active' : ''}`}
            onClick={() => onChange(item.key)}
          >
            {item.icon && <span className="hevi-tabbar__icon">{item.icon}</span>}
            {item.label}
            {item.badge != null && <span className="hevi-tabbar__badge">{item.badge}</span>}
          </button>
        ))}
      </div>
    );
  }

  // Default: underline
  return (
    <div className={`hevi-tabbar hevi-tabbar--underline ${className}`}>
      <nav className="hevi-tabbar__nav">
        {items.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`hevi-tabbar__item ${active === item.key ? 'hevi-tabbar__item--active' : ''}`}
            onClick={() => onChange(item.key)}
          >
            {item.icon && <span className="hevi-tabbar__icon">{item.icon}</span>}
            {item.label}
            {item.badge != null && <span className="hevi-tabbar__badge">{item.badge}</span>}
          </button>
        ))}
      </nav>
    </div>
  );
}
