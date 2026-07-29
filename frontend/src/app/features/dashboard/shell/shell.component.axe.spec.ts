import { ComponentFixture, TestBed } from '@angular/core/testing';
import { BreakpointObserver } from '@angular/cdk/layout';
import { of } from 'rxjs';
import { ShellComponent } from './shell.component';
import { axe } from '@core/testing/axe-setup';

describe('ShellComponent Accessibility (axe)', () => {
  let component: ShellComponent;
  let fixture: ComponentFixture<ShellComponent>;
  let breakpointObserverSpy: jasmine.SpyObj<BreakpointObserver>;

  beforeEach(async () => {
    breakpointObserverSpy = jasmine.createSpyObj('BreakpointObserver', ['observe']);
    breakpointObserverSpy.observe.and.returnValue(
      of({ matches: false, breakpoints: {}, mediaQuery: '', media: '' }),
    );

    await TestBed.configureTestingModule({
      imports: [ShellComponent],
      providers: [{ provide: BreakpointObserver, useValue: breakpointObserverSpy }],
    }).compileComponents();

    fixture = TestBed.createComponent(ShellComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should not have axe violations in shell layout', async () => {
    const results = await axe(fixture.nativeElement);
    expect(results).toHaveNoViolations();
  });
});
