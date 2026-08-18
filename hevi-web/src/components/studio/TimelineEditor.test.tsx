import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TimelineEditor } from './TimelineEditor';

describe('TimelineEditor', () => {
  it('renders tracks and generate control', () => {
    render(<TimelineEditor />);
    expect(screen.getByRole('heading', { name: '时间线' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '从产线生成' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '收缝' })).toBeInTheDocument();
    expect(screen.getByText('画面')).toBeInTheDocument();
    expect(screen.getByText('对白')).toBeInTheDocument();
    expect(screen.getByText('字幕')).toBeInTheDocument();
  });
});
